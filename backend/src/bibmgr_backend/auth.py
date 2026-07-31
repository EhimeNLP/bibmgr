"""Passwordless email authentication and session handling."""

from __future__ import annotations

from base64 import urlsafe_b64encode
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from enum import Enum
from hashlib import sha256
import hmac
import os
from pathlib import Path
import secrets
import smtplib
import ssl
import uuid
from typing import Protocol

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .db_models import (
    EmailLoginChallenge,
    UserRecord,
    UserSessionRecord,
    utc_now,
)


LOGIN_CODE_DIGITS = 8
LOGIN_CODE_LIFETIME = timedelta(minutes=10)
LOGIN_CODE_MAX_ATTEMPTS = 5
EMAIL_REQUEST_COOLDOWN = timedelta(seconds=60)
IP_REQUEST_WINDOW = timedelta(hours=1)
IP_REQUEST_LIMIT = 30
SESSION_LIFETIME = timedelta(days=7)
DEFAULT_EMAIL_DOMAIN = "example.test"
DEFAULT_SESSION_COOKIE = "bibmgr_session"
_DEVELOPMENT_AUTH_SECRET = secrets.token_bytes(32)


class LoginCodeMailer(Protocol):
    def send_login_code(
        self,
        *,
        recipient: str,
        code: str,
        expires_in_minutes: int,
    ) -> None: ...


class AuthenticationError(RuntimeError):
    """Base class for application-owned authentication failures."""


class AuthenticationRequiredError(AuthenticationError):
    """The request does not carry a valid authenticated session."""


class CsrfValidationError(AuthenticationError):
    """A state-changing request failed CSRF validation."""


class AuthenticationRateLimitError(AuthenticationError):
    """Too many authentication codes were requested."""

    def __init__(self, retry_after: int = 60) -> None:
        super().__init__("Too many authentication attempts.")
        self.retry_after = retry_after


class EmailDeliveryError(AuthenticationError):
    """The configured SMTP transport could not deliver a login code."""


class SmtpSecurity(str, Enum):
    """Supported SMTP connection security modes."""

    PLAIN = "plain"
    STARTTLS = "starttls"
    IMPLICIT_TLS = "implicit_tls"


_SMTP_DEFAULT_PORTS = {
    SmtpSecurity.PLAIN: 25,
    SmtpSecurity.STARTTLS: 587,
    SmtpSecurity.IMPLICIT_TLS: 465,
}


@dataclass(frozen=True)
class AuthenticatedSession:
    user: UserRecord
    session: UserSessionRecord
    token: str


@dataclass(frozen=True)
class LoginCodeDelivery:
    challenge_id: uuid.UUID
    recipient: str
    code: str
    expires_in_minutes: int


class SmtpLoginCodeMailer:
    """Send login codes using the configured SMTP relay."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        username: str | None = None,
        password: str | None = None,
        security: SmtpSecurity | str = SmtpSecurity.PLAIN,
        ca_file: str | None = None,
    ) -> None:
        normalized_host = host.strip()
        normalized_sender = normalize_email(sender)
        if not normalized_host:
            raise RuntimeError("BIBMGR_SMTP_HOST must not be empty.")
        if normalized_sender is None:
            raise RuntimeError(
                "BIBMGR_EMAIL_FROM must be one complete email address."
            )
        try:
            normalized_security = SmtpSecurity(security)
        except ValueError as error:
            supported = ", ".join(mode.value for mode in SmtpSecurity)
            raise RuntimeError(
                f"BIBMGR_SMTP_SECURITY must be one of: {supported}."
            ) from error
        normalized_username = username.strip() if username else None
        normalized_password = password if password else None
        if not 1 <= port <= 65535:
            raise RuntimeError(
                "BIBMGR_SMTP_PORT must be between 1 and 65535."
            )
        if bool(normalized_username) != bool(normalized_password):
            raise RuntimeError(
                "BIBMGR_SMTP_USERNAME and an SMTP password must be "
                "configured together."
            )
        if (
            normalized_security is SmtpSecurity.PLAIN
            and normalized_username is not None
        ):
            raise RuntimeError(
                "SMTP authentication requires starttls or implicit_tls."
            )
        if normalized_security is SmtpSecurity.PLAIN and ca_file:
            raise RuntimeError(
                "BIBMGR_SMTP_CA_FILE requires starttls or implicit_tls."
            )
        self.host = normalized_host
        self.port = port
        self.sender = normalized_sender
        self.username = normalized_username
        self.password = normalized_password
        self.security = normalized_security
        self.ca_file = ca_file or None

    @classmethod
    def from_environment(cls) -> SmtpLoginCodeMailer:
        production = os.environ.get("BIBMGR_ENV") == "production"
        host = os.environ.get("BIBMGR_SMTP_HOST")
        if production and not host:
            raise RuntimeError(
                "BIBMGR_SMTP_HOST is required in production."
            )
        sender = os.environ.get("BIBMGR_EMAIL_FROM")
        if production and not sender:
            raise RuntimeError(
                "BIBMGR_EMAIL_FROM is required in production."
            )
        if "BIBMGR_SMTP_STARTTLS" in os.environ:
            raise RuntimeError(
                "BIBMGR_SMTP_STARTTLS has been replaced by "
                "BIBMGR_SMTP_SECURITY."
            )
        configured_security = os.environ.get("BIBMGR_SMTP_SECURITY")
        if production and not configured_security:
            raise RuntimeError(
                "BIBMGR_SMTP_SECURITY is required in production."
            )
        try:
            security = SmtpSecurity(
                configured_security or SmtpSecurity.PLAIN.value
            )
        except ValueError as error:
            supported = ", ".join(mode.value for mode in SmtpSecurity)
            raise RuntimeError(
                f"BIBMGR_SMTP_SECURITY must be one of: {supported}."
            ) from error
        configured_port = os.environ.get("BIBMGR_SMTP_PORT")
        if configured_port is None:
            port = _SMTP_DEFAULT_PORTS[security] if production else 1025
        else:
            try:
                port = int(configured_port)
            except ValueError as error:
                raise RuntimeError(
                    "BIBMGR_SMTP_PORT must be an integer."
                ) from error
        return cls(
            host=host or "127.0.0.1",
            port=port,
            sender=sender or f"bibmgr@{DEFAULT_EMAIL_DOMAIN}",
            username=os.environ.get("BIBMGR_SMTP_USERNAME"),
            password=(
                os.environ.get("BIBMGR_SMTP_PASSWORD")
                or _file_secret(
                    "BIBMGR_SMTP_PASSWORD_FILE", allow_empty=True
                )
            ),
            security=security,
            ca_file=os.environ.get("BIBMGR_SMTP_CA_FILE"),
        )

    def _tls_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context(cafile=self.ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        return context

    def send_login_code(
        self,
        *,
        recipient: str,
        code: str,
        expires_in_minutes: int,
    ) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = "BibMgR login code"
        message.set_content(
            "Use the following code to sign in to BibMgR:\n\n"
            f"{code}\n\n"
            "This code can be used once and expires in "
            f"{expires_in_minutes} minutes.\n"
            "If you did not request this code, you can safely ignore "
            "this email."
        )

        try:
            if self.security is SmtpSecurity.IMPLICIT_TLS:
                connection = smtplib.SMTP_SSL(
                    self.host,
                    self.port,
                    timeout=10,
                    context=self._tls_context(),
                )
            else:
                connection = smtplib.SMTP(
                    self.host, self.port, timeout=10
                )
            with connection as smtp:
                if self.security is SmtpSecurity.STARTTLS:
                    smtp.ehlo()
                    smtp.starttls(context=self._tls_context())
                    smtp.ehlo()
                if self.username:
                    assert self.password is not None
                    smtp.login(self.username, self.password)
                smtp.send_message(
                    message,
                    from_addr=self.sender,
                    to_addrs=[recipient],
                )
        except (OSError, smtplib.SMTPException) as error:
            raise EmailDeliveryError(
                "The login email could not be delivered."
            ) from error


class AuthenticationManager:
    """Own passwordless login challenges and opaque database sessions."""

    def __init__(
        self,
        *,
        mailer: LoginCodeMailer | None = None,
        secret: bytes | None = None,
        allowed_domain: str | None = None,
        allowed_emails: set[str] | None = None,
        now: Callable[[], datetime] = utc_now,
        code_generator: Callable[[], str] | None = None,
        session_token_generator: Callable[[], str] | None = None,
        secure_cookie: bool | None = None,
        cookie_path: str | None = None,
    ) -> None:
        self.mailer = mailer or SmtpLoginCodeMailer.from_environment()
        self.secret = secret or authentication_secret()
        configured_domain = allowed_domain or os.environ.get(
            "BIBMGR_AUTH_EMAIL_DOMAIN"
        )
        if (
            os.environ.get("BIBMGR_ENV") == "production"
            and not configured_domain
        ):
            raise RuntimeError(
                "BIBMGR_AUTH_EMAIL_DOMAIN is required in production."
            )
        self.allowed_domain = (
            configured_domain or DEFAULT_EMAIL_DOMAIN
        ).casefold()
        configured_allowed_emails = (
            allowed_emails
            if allowed_emails is not None
            else allowed_email_exceptions()
        )
        self.allowed_emails = frozenset(
            normalized
            for value in configured_allowed_emails
            if (normalized := normalize_email(value)) is not None
        )
        self.now = now
        self.code_generator = code_generator or _generate_login_code
        self.session_token_generator = (
            session_token_generator
            or (lambda: secrets.token_urlsafe(32))
        )
        self.secure_cookie = (
            secure_cookie
            if secure_cookie is not None
            else _environment_flag(
                "BIBMGR_COOKIE_SECURE",
                default=os.environ.get("BIBMGR_ENV") == "production",
            )
        )
        self.cookie_name = os.environ.get(
            "BIBMGR_SESSION_COOKIE", DEFAULT_SESSION_COOKIE
        )
        configured_cookie_path = (
            cookie_path
            if cookie_path is not None
            else os.environ.get("BIBMGR_COOKIE_PATH", "/")
        )
        if not configured_cookie_path.startswith("/") or any(
            character in configured_cookie_path
            for character in ("\r", "\n", ";", ",")
        ):
            raise RuntimeError(
                "BIBMGR_COOKIE_PATH must be an absolute URL path."
            )
        self.cookie_path = configured_cookie_path.rstrip("/") or "/"

    def reserve_login_code(
        self,
        session: Session,
        *,
        email: str,
        request_ip: str | None,
    ) -> LoginCodeDelivery | None:
        normalized_email = normalize_email(email)
        if not self._is_allowed_email(normalized_email):
            return None
        assert normalized_email is not None

        self._lock_login_request_slots(
            session,
            email=normalized_email,
            request_ip=request_ip,
        )
        now = self.now()
        latest_request = session.scalar(
            select(EmailLoginChallenge)
            .where(EmailLoginChallenge.email == normalized_email)
            .order_by(EmailLoginChallenge.requested_at.desc())
            .limit(1)
        )
        if (
            latest_request is not None
            and _as_utc(latest_request.requested_at)
            >= now - EMAIL_REQUEST_COOLDOWN
        ):
            raise AuthenticationRateLimitError()

        if request_ip:
            recent_ip_requests = session.scalar(
                select(func.count())
                .select_from(EmailLoginChallenge)
                .where(
                    EmailLoginChallenge.request_ip == request_ip,
                    EmailLoginChallenge.requested_at
                    >= now - IP_REQUEST_WINDOW,
                )
            )
            if (recent_ip_requests or 0) >= IP_REQUEST_LIMIT:
                raise AuthenticationRateLimitError()

        user = session.scalar(
            select(UserRecord).where(UserRecord.email == normalized_email)
        )
        if user is not None and user.status != "active":
            return None

        session.execute(
            update(EmailLoginChallenge)
            .where(
                EmailLoginChallenge.email == normalized_email,
                EmailLoginChallenge.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )

        code = self.code_generator()
        challenge_id = uuid.uuid4()
        challenge = EmailLoginChallenge(
            id=challenge_id,
            email=normalized_email,
            code_digest=self._code_digest(
                challenge_id, normalized_email, code
            ),
            request_ip=request_ip,
            attempts=0,
            requested_at=now,
            expires_at=now + LOGIN_CODE_LIFETIME,
        )
        session.add(challenge)
        session.flush()
        return LoginCodeDelivery(
            challenge_id=challenge_id,
            recipient=normalized_email,
            code=code,
            expires_in_minutes=int(
                LOGIN_CODE_LIFETIME.total_seconds() / 60
            ),
        )

    def deliver_login_code(self, delivery: LoginCodeDelivery) -> None:
        self.mailer.send_login_code(
            recipient=delivery.recipient,
            code=delivery.code,
            expires_in_minutes=delivery.expires_in_minutes,
        )

    def mark_login_delivery_failed(
        self,
        session: Session,
        challenge_id: uuid.UUID,
    ) -> None:
        session.execute(
            update(EmailLoginChallenge)
            .where(
                EmailLoginChallenge.id == challenge_id,
                EmailLoginChallenge.consumed_at.is_(None),
            )
            .values(consumed_at=self.now())
        )

    def _lock_login_request_slots(
        self,
        session: Session,
        *,
        email: str,
        request_ip: str | None,
    ) -> None:
        if session.get_bind().dialect.name != "postgresql":
            return
        lock_values = [("email", email)]
        if request_ip:
            lock_values.append(("ip", request_ip))
        for namespace, value in lock_values:
            session.scalar(
                select(
                    func.pg_advisory_xact_lock(
                        _advisory_lock_key(namespace, value)
                    )
                )
            )

    def verify_login(
        self,
        session: Session,
        *,
        email: str,
        code: str,
    ) -> AuthenticatedSession | None:
        normalized_email = normalize_email(email)
        if not self._is_allowed_email(normalized_email):
            return None

        now = self.now()
        challenge = session.scalar(
            select(EmailLoginChallenge)
            .where(
                EmailLoginChallenge.email == normalized_email,
                EmailLoginChallenge.consumed_at.is_(None),
                EmailLoginChallenge.expires_at > now,
            )
            .order_by(EmailLoginChallenge.requested_at.desc())
            .with_for_update()
            .limit(1)
        )
        if challenge is None:
            return None

        expected_digest = self._code_digest(
            challenge.id, normalized_email, code
        )
        if not hmac.compare_digest(
            challenge.code_digest, expected_digest
        ):
            challenge.attempts += 1
            if challenge.attempts >= LOGIN_CODE_MAX_ATTEMPTS:
                challenge.consumed_at = now
            return None

        challenge.consumed_at = now
        user = session.scalar(
            select(UserRecord)
            .where(UserRecord.email == normalized_email)
            .with_for_update()
        )
        if user is not None and user.status != "active":
            return None
        if user is None:
            user = UserRecord(
                email=normalized_email,
                status="active",
                first_verified_at=now,
                last_login_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            session.flush()
        else:
            user.last_login_at = now
            user.updated_at = now

        token = self.session_token_generator()
        user_session = UserSessionRecord(
            user_id=user.id,
            token_digest=_token_digest(token),
            created_at=now,
            expires_at=now + SESSION_LIFETIME,
        )
        session.add(user_session)
        session.flush()
        return AuthenticatedSession(
            user=user,
            session=user_session,
            token=token,
        )

    def authenticate(
        self, session: Session, token: str | None
    ) -> AuthenticatedSession | None:
        if not token:
            return None
        record = session.scalar(
            select(UserSessionRecord).where(
                UserSessionRecord.token_digest == _token_digest(token),
                UserSessionRecord.revoked_at.is_(None),
                UserSessionRecord.expires_at > self.now(),
            )
        )
        if record is None or record.user.status != "active":
            return None
        return AuthenticatedSession(
            user=record.user,
            session=record,
            token=token,
        )

    def require_write_session(
        self,
        session: Session,
        *,
        token: str | None,
        csrf_token: str | None,
    ) -> AuthenticatedSession:
        authenticated = self.authenticate(session, token)
        if authenticated is None:
            raise AuthenticationRequiredError(
                "Login is required for this operation."
            )
        expected_csrf = self.csrf_token(authenticated.token)
        if not csrf_token or not hmac.compare_digest(
            csrf_token, expected_csrf
        ):
            raise CsrfValidationError("CSRF validation failed.")
        return authenticated

    def revoke(
        self, authenticated: AuthenticatedSession
    ) -> None:
        authenticated.session.revoked_at = self.now()

    def csrf_token(self, session_token: str) -> str:
        digest = hmac.digest(
            self.secret,
            f"csrf:{session_token}".encode(),
            "sha256",
        )
        return urlsafe_b64encode(digest).decode().rstrip("=")

    def _code_digest(
        self,
        challenge_id: uuid.UUID,
        email: str,
        code: str,
    ) -> str:
        return hmac.new(
            self.secret,
            f"{challenge_id}:{email}:{code}".encode(),
            sha256,
        ).hexdigest()

    def _is_allowed_email(self, email: str | None) -> bool:
        if email is None:
            return False
        if email in self.allowed_emails:
            return True
        _local, separator, domain = email.rpartition("@")
        return bool(separator) and domain == self.allowed_domain


def authentication_secret() -> bytes:
    configured = os.environ.get("BIBMGR_AUTH_SECRET") or _file_secret(
        "BIBMGR_AUTH_SECRET_FILE"
    )
    if configured:
        secret = configured.encode()
        if os.environ.get("BIBMGR_ENV") == "production" and len(secret) < 32:
            raise RuntimeError(
                "BIBMGR_AUTH_SECRET must contain at least 32 bytes "
                "in production."
            )
        return secret
    if os.environ.get("BIBMGR_ENV") == "production":
        raise RuntimeError(
            "BIBMGR_AUTH_SECRET is required in production."
        )
    return _DEVELOPMENT_AUTH_SECRET


def allowed_email_exceptions() -> set[str]:
    configured = os.environ.get("BIBMGR_AUTH_ALLOWED_EMAILS", "")
    return {
        value.strip()
        for value in configured.replace("\n", ",").split(",")
        if value.strip()
    }


def normalize_email(value: str) -> str | None:
    email = value.strip().casefold()
    if len(email) > 320 or email.count("@") != 1:
        return None
    local, domain = email.split("@", 1)
    if not local or len(local) > 64 or not domain:
        return None
    if any(character.isspace() or ord(character) < 33 for character in email):
        return None
    return email


def _generate_login_code() -> str:
    return f"{secrets.randbelow(10**LOGIN_CODE_DIGITS):0{LOGIN_CODE_DIGITS}d}"


def _token_digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _advisory_lock_key(namespace: str, value: str) -> int:
    digest = sha256(f"{namespace}\0{value}".encode()).digest()
    unsigned = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return unsigned if unsigned < 2**63 else unsigned - 2**64


def _environment_flag(name: str, *, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.casefold() in {"1", "true", "yes", "on"}


def _file_secret(
    environment_name: str, *, allow_empty: bool = False
) -> str | None:
    path = os.environ.get(environment_name)
    if not path:
        return None
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value and not allow_empty:
        raise RuntimeError(f"{environment_name} points to an empty file.")
    return value
