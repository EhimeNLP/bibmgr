from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bibmgr_backend.app import create_app
from bibmgr_backend.auth import (
    AuthenticationManager,
    SmtpLoginCodeMailer,
    allowed_email_exceptions,
    authentication_secret,
    normalize_email,
)
from bibmgr_backend.db_models import (
    Base,
    EmailLoginChallenge,
    UserRecord,
    UserSessionRecord,
)


class UnusedEngine:
    def analyze(
        self, source: str, profile: str, mode: str
    ) -> dict[str, Any]:
        return {"schema_version": "1"}

    def apply_fixes(
        self,
        source: str,
        source_revision: str,
        fix_ids: list[str],
        profile: str,
    ) -> dict[str, Any]:
        return {"schema_version": "1"}

    def validate_for_registration(
        self, source: str, policy: str
    ) -> dict[str, Any]:
        raise AssertionError("protected write reached the engine")

    def canonicalize_for_storage(
        self, source: str, policy: str
    ) -> dict[str, Any]:
        raise AssertionError("protected write reached the engine")

    def export_profiles(self) -> dict[str, Any]:
        return {"schema_version": "1"}

    def export_source(
        self, source: str, profile: str
    ) -> dict[str, Any]:
        return {"schema_version": "1"}


class CapturingMailer:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, int]] = []

    def send_login_code(
        self,
        *,
        recipient: str,
        code: str,
        expires_in_minutes: int,
    ) -> None:
        self.messages.append((recipient, code, expires_in_minutes))


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 27, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


def build_client(
    *,
    allowed_emails: set[str] | None = None,
    cookie_path: str = "/",
) -> tuple[
    TestClient,
    CapturingMailer,
    MutableClock,
    sessionmaker[Session],
]:
    database = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(database)
    sessions = sessionmaker(
        bind=database, class_=Session, expire_on_commit=False
    )
    mailer = CapturingMailer()
    clock = MutableClock()
    authentication = AuthenticationManager(
        mailer=mailer,
        secret=b"authentication-api-test-secret",
        now=clock,
        code_generator=lambda: "12345678",
        session_token_generator=lambda: "opaque-test-session-token",
        secure_cookie=False,
        allowed_emails=allowed_emails,
        cookie_path=cookie_path,
    )
    client = TestClient(
        create_app(
            UnusedEngine(),
            session_factory=sessions,
            authentication=authentication,
        )
    )
    return client, mailer, clock, sessions


def test_email_login_creates_session_and_logout_revokes_it() -> None:
    client, mailer, _clock, sessions = build_client()

    refused = client.post(
        "/auth/email/start",
        json={"email": "researcher@example.com"},
    )
    started = client.post(
        "/auth/email/start",
        json={"email": "Researcher@AI.CS.EHIME-U.AC.JP"},
    )

    assert refused.status_code == 202
    assert started.status_code == 202
    assert mailer.messages == [
        ("researcher@ai.cs.ehime-u.ac.jp", "12345678", 10)
    ]

    verified = client.post(
        "/auth/email/verify",
        json={
            "email": "researcher@ai.cs.ehime-u.ac.jp",
            "code": "12345678",
        },
    )

    assert verified.status_code == 200
    payload = verified.json()
    assert payload["authenticated"] is True
    assert payload["user"]["email"] == "researcher@ai.cs.ehime-u.ac.jp"
    assert payload["csrfToken"]
    assert client.get("/auth/session").json() == payload

    reused = client.post(
        "/auth/email/verify",
        json={
            "email": "researcher@ai.cs.ehime-u.ac.jp",
            "code": "12345678",
        },
    )
    assert reused.status_code == 401

    missing_csrf = client.post("/auth/logout")
    assert missing_csrf.status_code == 403

    logged_out = client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": payload["csrfToken"]},
    )
    assert logged_out.status_code == 204
    assert client.get("/auth/session").json()["authenticated"] is False

    with sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(UserRecord)
        ) == 1
        stored_session = session.scalar(select(UserSessionRecord))
        assert stored_session is not None
        assert stored_session.token_digest != "opaque-test-session-token"
        assert stored_session.revoked_at is not None


def test_session_cookie_can_be_scoped_to_a_proxy_subpath() -> None:
    client, _mailer, _clock, _sessions = build_client(
        cookie_path="/bibmgr/"
    )
    email = "member@ai.cs.ehime-u.ac.jp"
    assert client.post(
        "/auth/email/start", json={"email": email}
    ).status_code == 202

    verified = client.post(
        "/auth/email/verify",
        json={"email": email, "code": "12345678"},
    )

    assert verified.status_code == 200
    assert "Path=/bibmgr" in verified.headers["set-cookie"]


def test_login_code_is_rate_limited_and_expires() -> None:
    client, mailer, clock, sessions = build_client()
    email = "member@ai.cs.ehime-u.ac.jp"

    assert client.post(
        "/auth/email/start", json={"email": email}
    ).status_code == 202
    limited = client.post(
        "/auth/email/start", json={"email": email}
    )
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"

    clock.advance(timedelta(minutes=11))
    expired = client.post(
        "/auth/email/verify",
        json={"email": email, "code": mailer.messages[0][1]},
    )
    assert expired.status_code == 401

    with sessions() as session:
        challenge = session.scalar(select(EmailLoginChallenge))
        assert challenge is not None
        assert challenge.code_digest != mailer.messages[0][1]


def test_exact_external_email_allowlist_is_additive() -> None:
    client, mailer, _clock, _sessions = build_client(
        allowed_emails={"Visitor@Example.ORG"}
    )

    assert client.post(
        "/auth/email/start",
        json={"email": "visitor@example.org"},
    ).status_code == 202
    assert client.post(
        "/auth/email/start",
        json={"email": "other@example.org"},
    ).status_code == 202
    assert client.post(
        "/auth/email/start",
        json={"email": "member@ai.cs.ehime-u.ac.jp"},
    ).status_code == 202
    assert [message[0] for message in mailer.messages] == [
        "visitor@example.org",
        "member@ai.cs.ehime-u.ac.jp",
    ]


def test_reference_writes_require_session_and_csrf_but_reads_are_public() -> None:
    client, mailer, clock, _sessions = build_client()
    source = "@article{demo, title={Demo}}"

    assert client.get("/references").status_code == 200
    assert client.get("/reference-history").status_code == 401
    unauthenticated = client.post(
        "/references",
        json={"bibtex": source, "source": "manual"},
    )
    assert unauthenticated.status_code == 401
    assert (
        unauthenticated.json()["error"]["code"]
        == "authentication_required"
    )

    clock.advance(timedelta(minutes=1))
    client.post(
        "/auth/email/start",
        json={"email": "member@ai.cs.ehime-u.ac.jp"},
    )
    verified = client.post(
        "/auth/email/verify",
        json={
            "email": "member@ai.cs.ehime-u.ac.jp",
            "code": mailer.messages[-1][1],
        },
    )
    assert verified.status_code == 200

    missing_csrf = client.post(
        "/references",
        json={"bibtex": source, "source": "manual"},
    )
    assert missing_csrf.status_code == 403
    assert (
        missing_csrf.json()["error"]["code"]
        == "csrf_validation_failed"
    )


def test_production_requires_authentication_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIBMGR_ENV", "production")
    monkeypatch.delenv("BIBMGR_AUTH_SECRET", raising=False)
    monkeypatch.delenv("BIBMGR_AUTH_SECRET_FILE", raising=False)

    with pytest.raises(RuntimeError, match="BIBMGR_AUTH_SECRET"):
        authentication_secret()


def test_production_requires_a_strong_authentication_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIBMGR_ENV", "production")
    monkeypatch.setenv("BIBMGR_AUTH_SECRET", "too-short")

    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        authentication_secret()


def test_authentication_secret_can_be_read_from_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret_file = tmp_path / "auth_secret"
    secret_file.write_text("file-backed-auth-secret\n", encoding="utf-8")
    monkeypatch.delenv("BIBMGR_AUTH_SECRET", raising=False)
    monkeypatch.setenv("BIBMGR_AUTH_SECRET_FILE", str(secret_file))

    assert authentication_secret() == b"file-backed-auth-secret"


def test_production_smtp_requires_an_explicit_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIBMGR_ENV", "production")
    monkeypatch.delenv("BIBMGR_SMTP_HOST", raising=False)

    with pytest.raises(RuntimeError, match="BIBMGR_SMTP_HOST"):
        SmtpLoginCodeMailer.from_environment()


def test_email_normalization_rejects_ambiguous_addresses() -> None:
    assert (
        normalize_email(" Member@AI.CS.EHIME-U.AC.JP ")
        == "member@ai.cs.ehime-u.ac.jp"
    )
    assert normalize_email("member@@ai.cs.ehime-u.ac.jp") is None
    assert normalize_email("member\n@ai.cs.ehime-u.ac.jp") is None


def test_allowed_email_exceptions_parse_complete_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "BIBMGR_AUTH_ALLOWED_EMAILS",
        "visitor@example.org,\n collaborator@example.net ",
    )
    assert allowed_email_exceptions() == {
        "visitor@example.org",
        "collaborator@example.net",
    }


def test_smtp_mailer_sends_the_login_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: list[Any] = []

    class FakeSmtp:
        def __init__(
            self, host: str, port: int, timeout: int
        ) -> None:
            assert (host, port, timeout) == ("smtp.example", 587, 10)

        def __enter__(self) -> FakeSmtp:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def starttls(self, *, context: Any) -> None:
            assert context is not None

        def login(self, username: str, password: str) -> None:
            assert (username, password) == ("smtp-user", "smtp-password")

        def send_message(self, message: Any) -> None:
            sent_messages.append(message)

    monkeypatch.setattr("bibmgr_backend.auth.smtplib.SMTP", FakeSmtp)
    mailer = SmtpLoginCodeMailer(
        host="smtp.example",
        port=587,
        sender="bibmgr@ai.cs.ehime-u.ac.jp",
        username="smtp-user",
        password="smtp-password",
        starttls=True,
    )

    mailer.send_login_code(
        recipient="member@ai.cs.ehime-u.ac.jp",
        code="12345678",
        expires_in_minutes=10,
    )

    assert len(sent_messages) == 1
    assert sent_messages[0]["To"] == "member@ai.cs.ehime-u.ac.jp"
    content = sent_messages[0].get_content()
    assert sent_messages[0]["Subject"] == "BibMgR login code"
    assert "Use the following code to sign in to BibMgR:" in content
    assert "12345678" in content
    assert "expires in 10 minutes" in content
    assert "If you did not request this code" in content
    assert "ログイン" not in content
