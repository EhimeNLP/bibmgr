from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import ssl
from typing import Any

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bibmgr_backend.app import create_app
from bibmgr_backend.auth import (
    AuthenticationManager,
    EmailDeliveryError,
    SmtpLoginCodeMailer,
    SmtpSecurity,
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
from bibmgr_backend.security import RateLimitPolicy, RequestProtection


class UnusedEngine:
    def analyze(
        self,
        source: str,
        profile: str,
        mode: str,
        *,
        venue_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"schema_version": "1"}

    def apply_fixes(
        self,
        source: str,
        source_revision: str,
        fix_ids: list[str],
        profile: str,
        *,
        venue_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"schema_version": "1"}

    def validate_for_registration(
        self,
        source: str,
        policy: str,
        *,
        venue_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise AssertionError("protected write reached the engine")

    def canonicalize_for_storage(
        self,
        source: str,
        policy: str,
        *,
        venue_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise AssertionError("protected write reached the engine")

    def export_profiles(self) -> dict[str, Any]:
        return {"schema_version": "1"}

    def export_source(
        self,
        source: str,
        profile: str,
        *,
        venue_name_style: str = "full",
        profile_data: dict[str, Any] | None = None,
        venue_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"schema_version": "1"}

    def builtin_configuration(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "export_profiles": [],
            "venue_registry": {"schema_version": "1", "venues": []},
        }

    def validate_export_profile(
        self, profile_data: dict[str, Any]
    ) -> dict[str, Any]:
        return {"schema_version": "1", "profile": profile_data}

    def validate_venue_registry(
        self, venue_registry: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "venue_registry": venue_registry,
        }


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


class FailingMailer(CapturingMailer):
    def send_login_code(
        self,
        *,
        recipient: str,
        code: str,
        expires_in_minutes: int,
    ) -> None:
        raise EmailDeliveryError("The login email could not be delivered.")


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
    mailer: CapturingMailer | None = None,
    request_protection: RequestProtection | None = None,
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
    selected_mailer = mailer or CapturingMailer()
    clock = MutableClock()
    authentication = AuthenticationManager(
        mailer=selected_mailer,
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
            request_protection=request_protection,
        )
    )
    return client, selected_mailer, clock, sessions


def test_email_login_creates_session_and_logout_revokes_it() -> None:
    client, mailer, _clock, sessions = build_client()

    refused = client.post(
        "/auth/email/start",
        json={"email": "researcher@example.com"},
    )
    started = client.post(
        "/auth/email/start",
        json={"email": "Researcher@EXAMPLE.TEST"},
    )

    assert refused.status_code == 202
    assert started.status_code == 202
    assert mailer.messages == [
        ("researcher@example.test", "12345678", 10)
    ]

    verified = client.post(
        "/auth/email/verify",
        json={
            "email": "researcher@example.test",
            "code": "12345678",
        },
    )

    assert verified.status_code == 200
    payload = verified.json()
    assert payload["authenticated"] is True
    assert payload["user"]["email"] == "researcher@example.test"
    assert payload["csrfToken"]
    assert client.get("/auth/session").json() == payload

    reused = client.post(
        "/auth/email/verify",
        json={
            "email": "researcher@example.test",
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


def test_authenticated_requests_are_rate_limited_per_user() -> None:
    protection = RequestProtection(
        global_policy=RateLimitPolicy(
            "global", requests_per_minute=10_000, burst=100
        ),
        authenticated_policy=RateLimitPolicy(
            "authenticated", requests_per_minute=1, burst=1
        ),
    )
    client, mailer, _clock, _sessions = build_client(
        request_protection=protection
    )
    email = "member@example.test"
    assert client.post(
        "/auth/email/start", json={"email": email}
    ).status_code == 202
    assert client.post(
        "/auth/email/verify",
        json={"email": email, "code": mailer.messages[0][1]},
    ).status_code == 200

    assert client.get("/bibtex/export/profiles").status_code == 200
    limited = client.get("/bibtex/export/profiles")

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert limited.json()["error"]["code"] == "rate_limited"


def test_authenticated_writes_have_a_separate_rate_limit() -> None:
    protection = RequestProtection(
        global_policy=RateLimitPolicy(
            "global", requests_per_minute=10_000, burst=100
        ),
        authenticated_policy=RateLimitPolicy(
            "authenticated", requests_per_minute=10_000, burst=100
        ),
        authenticated_write_policy=RateLimitPolicy(
            "write", requests_per_minute=1, burst=1
        ),
    )
    client, mailer, _clock, _sessions = build_client(
        request_protection=protection
    )
    email = "member@example.test"
    assert client.post(
        "/auth/email/start", json={"email": email}
    ).status_code == 202
    login = client.post(
        "/auth/email/verify",
        json={"email": email, "code": mailer.messages[0][1]},
    )
    assert login.status_code == 200
    csrf_token = login.json()["csrfToken"]

    headers = {
        "X-CSRF-Token": csrf_token,
        "If-Match": f"sha256:{'0' * 64}",
    }
    missing_reference = (
        "/references/00000000-0000-0000-0000-000000000001"
    )
    assert client.delete(
        missing_reference,
        headers=headers,
    ).status_code == 404

    limited = client.delete(missing_reference, headers=headers)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"


def test_session_cookie_can_be_scoped_to_a_proxy_subpath() -> None:
    client, _mailer, _clock, _sessions = build_client(
        cookie_path="/bibmgr/"
    )
    email = "member@example.test"
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
    email = "member@example.test"

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


def test_failed_delivery_consumes_challenge_and_preserves_request_slot() -> None:
    failing_mailer = FailingMailer()
    client, _mailer, _clock, sessions = build_client(
        mailer=failing_mailer
    )
    email = "member@example.test"

    failed = client.post("/auth/email/start", json={"email": email})

    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "email_delivery_failed"
    with sessions() as session:
        challenge = session.scalar(select(EmailLoginChallenge))
        assert challenge is not None
        assert challenge.consumed_at is not None

    limited = client.post("/auth/email/start", json={"email": email})
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"


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
        json={"email": "member@example.test"},
    ).status_code == 202
    assert [message[0] for message in mailer.messages] == [
        "visitor@example.org",
        "member@example.test",
    ]


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/references", None),
        ("GET", "/references/page", None),
        (
            "GET",
            "/references/00000000-0000-0000-0000-000000000001",
            None,
        ),
        ("GET", "/reference-history", None),
        ("GET", "/reference-history/page", None),
        (
            "GET",
            (
                "/references/00000000-0000-0000-0000-000000000001"
                "/history"
            ),
            None,
        ),
        ("GET", "/bibtex/export/profiles", None),
        ("GET", "/settings/configuration", None),
        (
            "GET",
            "/settings/configuration-history?kind=export_profile",
            None,
        ),
        ("POST", "/bibtex/analyze", {"source": "@misc{demo}"}),
        (
            "POST",
            "/bibtex/fixes/apply",
            {
                "source": "@misc{demo}",
                "source_revision": f"sha256:{'0' * 64}",
                "fix_ids": ["fix"],
            },
        ),
        (
            "POST",
            "/bibtex/registration/validate",
            {"source": "@misc{demo}"},
        ),
        (
            "POST",
            "/bibtex/registration/canonicalize",
            {"source": "@misc{demo}"},
        ),
        (
            "POST",
            "/bibtex/export",
            {"source": "@misc{demo}"},
        ),
    ],
)
def test_reads_and_bibtex_tools_require_authentication(
    method: str,
    path: str,
    payload: dict[str, Any] | None,
) -> None:
    client, _mailer, _clock, _sessions = build_client()

    response = client.request(method, path, json=payload)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_application_access_requires_session_and_writes_require_csrf() -> None:
    client, mailer, clock, _sessions = build_client()
    source = "@article{demo, title={Demo}}"

    assert client.get("/references").status_code == 401
    assert client.get("/references/page").status_code == 401
    assert client.get("/bibtex/export/profiles").status_code == 401
    assert client.get("/settings/configuration").status_code == 401
    assert client.get(
        "/settings/configuration-history?kind=export_profile"
    ).status_code == 401
    assert client.post(
        "/bibtex/analyze",
        json={"source": source},
    ).status_code == 401
    assert client.get("/reference-history").status_code == 401
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
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
        json={"email": "member@example.test"},
    )
    verified = client.post(
        "/auth/email/verify",
        json={
            "email": "member@example.test",
            "code": mailer.messages[-1][1],
        },
    )
    assert verified.status_code == 200

    assert client.get("/references").status_code == 200
    assert client.get("/bibtex/export/profiles").status_code == 200
    assert client.get("/settings/configuration").status_code == 200
    assert client.get(
        "/settings/configuration-history?kind=export_profile"
    ).status_code == 200
    assert client.post(
        "/bibtex/analyze",
        json={"source": source},
    ).status_code == 200
    missing_csrf = client.post(
        "/references",
        json={"bibtex": source, "source": "manual"},
    )
    assert missing_csrf.status_code == 403
    assert (
        missing_csrf.json()["error"]["code"]
        == "csrf_validation_failed"
    )
    missing_delete_csrf = client.delete(
        "/settings/venues/custom-venue",
        params={"expected_revision": 1},
    )
    assert missing_delete_csrf.status_code == 403


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


def test_production_requires_an_explicit_email_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIBMGR_ENV", "production")
    monkeypatch.delenv("BIBMGR_AUTH_EMAIL_DOMAIN", raising=False)

    with pytest.raises(RuntimeError, match="BIBMGR_AUTH_EMAIL_DOMAIN"):
        AuthenticationManager(
            mailer=CapturingMailer(),
            secret=b"x" * 32,
        )


def test_production_smtp_requires_an_explicit_security_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIBMGR_ENV", "production")
    monkeypatch.setenv("BIBMGR_SMTP_HOST", "smtp.example")
    monkeypatch.setenv("BIBMGR_EMAIL_FROM", "bibmgr@example.test")
    monkeypatch.delenv("BIBMGR_SMTP_SECURITY", raising=False)
    monkeypatch.delenv("BIBMGR_SMTP_STARTTLS", raising=False)

    with pytest.raises(RuntimeError, match="BIBMGR_SMTP_SECURITY"):
        SmtpLoginCodeMailer.from_environment()


def test_production_smtp_requires_an_explicit_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIBMGR_ENV", "production")
    monkeypatch.setenv("BIBMGR_SMTP_HOST", "smtp.example")
    monkeypatch.delenv("BIBMGR_EMAIL_FROM", raising=False)

    with pytest.raises(RuntimeError, match="BIBMGR_EMAIL_FROM"):
        SmtpLoginCodeMailer.from_environment()


def test_development_smtp_defaults_to_mailpit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "BIBMGR_ENV",
        "BIBMGR_SMTP_HOST",
        "BIBMGR_SMTP_PORT",
        "BIBMGR_SMTP_SECURITY",
        "BIBMGR_SMTP_STARTTLS",
    ):
        monkeypatch.delenv(name, raising=False)

    mailer = SmtpLoginCodeMailer.from_environment()

    assert mailer.host == "127.0.0.1"
    assert mailer.port == 1025
    assert mailer.security is SmtpSecurity.PLAIN


@pytest.mark.parametrize(
    ("security", "expected_port"),
    [
        ("plain", 25),
        ("starttls", 587),
        ("implicit_tls", 465),
    ],
)
def test_production_smtp_uses_mode_specific_default_ports(
    monkeypatch: pytest.MonkeyPatch,
    security: str,
    expected_port: int,
) -> None:
    monkeypatch.setenv("BIBMGR_ENV", "production")
    monkeypatch.setenv("BIBMGR_SMTP_HOST", "smtp.example")
    monkeypatch.setenv("BIBMGR_EMAIL_FROM", "bibmgr@example.test")
    monkeypatch.setenv("BIBMGR_SMTP_SECURITY", security)
    monkeypatch.delenv("BIBMGR_SMTP_PORT", raising=False)
    monkeypatch.delenv("BIBMGR_SMTP_STARTTLS", raising=False)

    mailer = SmtpLoginCodeMailer.from_environment()

    assert mailer.security.value == security
    assert mailer.port == expected_port


@pytest.mark.parametrize("configured_port", ["not-a-port", "0", "65536"])
def test_smtp_environment_rejects_invalid_ports(
    monkeypatch: pytest.MonkeyPatch,
    configured_port: str,
) -> None:
    monkeypatch.setenv("BIBMGR_SMTP_PORT", configured_port)

    with pytest.raises(RuntimeError, match="BIBMGR_SMTP_PORT"):
        SmtpLoginCodeMailer.from_environment()


def test_smtp_environment_rejects_an_invalid_security_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIBMGR_SMTP_SECURITY", "tls")

    with pytest.raises(RuntimeError, match="must be one of"):
        SmtpLoginCodeMailer.from_environment()


def test_smtp_environment_rejects_deprecated_starttls_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIBMGR_SMTP_STARTTLS", "true")

    with pytest.raises(RuntimeError, match="has been replaced"):
        SmtpLoginCodeMailer.from_environment()


def test_smtp_configuration_rejects_insecure_authentication() -> None:
    with pytest.raises(RuntimeError, match="configured together"):
        SmtpLoginCodeMailer(
            host="smtp.example",
            port=587,
            sender="bibmgr@example.test",
            username="smtp-user",
            security=SmtpSecurity.STARTTLS,
        )
    with pytest.raises(RuntimeError, match="configured together"):
        SmtpLoginCodeMailer(
            host="smtp.example",
            port=587,
            sender="bibmgr@example.test",
            password="smtp-password",
            security=SmtpSecurity.STARTTLS,
        )
    with pytest.raises(RuntimeError, match="requires starttls"):
        SmtpLoginCodeMailer(
            host="smtp.example",
            port=25,
            sender="bibmgr@example.test",
            username="smtp-user",
            password="smtp-password",
            security=SmtpSecurity.PLAIN,
        )
    with pytest.raises(RuntimeError, match="CA_FILE requires"):
        SmtpLoginCodeMailer(
            host="relay.example",
            port=25,
            sender="bibmgr@example.test",
            security=SmtpSecurity.PLAIN,
            ca_file="/run/secrets/private-ca.pem",
        )
    with pytest.raises(RuntimeError, match="complete email address"):
        SmtpLoginCodeMailer(
            host="relay.example",
            port=25,
            sender="not-an-email-address",
            security=SmtpSecurity.PLAIN,
        )


def test_smtp_tls_context_uses_a_custom_ca_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_ca_files: list[str | None] = []

    def fake_create_default_context(
        *, cafile: str | None = None
    ) -> ssl.SSLContext:
        observed_ca_files.append(cafile)
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    monkeypatch.setattr(
        "bibmgr_backend.auth.ssl.create_default_context",
        fake_create_default_context,
    )
    mailer = SmtpLoginCodeMailer(
        host="smtp.example",
        port=465,
        sender="bibmgr@example.test",
        security=SmtpSecurity.IMPLICIT_TLS,
        ca_file="/run/secrets/private-ca.pem",
    )

    context = mailer._tls_context()

    assert observed_ca_files == ["/run/secrets/private-ca.pem"]
    assert context.minimum_version is ssl.TLSVersion.TLSv1_2


def test_email_normalization_rejects_ambiguous_addresses() -> None:
    assert (
        normalize_email(" Member@EXAMPLE.TEST ")
        == "member@example.test"
    )
    assert normalize_email("member@@example.test") is None
    assert normalize_email("member\n@example.test") is None


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


def test_starttls_mailer_sends_the_login_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: list[Any] = []
    ehlo_count = 0

    class FakeSmtp:
        def __init__(
            self, host: str, port: int, timeout: int
        ) -> None:
            assert (host, port, timeout) == ("smtp.example", 587, 10)

        def __enter__(self) -> FakeSmtp:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def ehlo(self) -> None:
            nonlocal ehlo_count
            ehlo_count += 1

        def starttls(self, *, context: Any) -> None:
            assert context.minimum_version is ssl.TLSVersion.TLSv1_2
            assert context.check_hostname
            assert context.verify_mode is ssl.CERT_REQUIRED

        def login(self, username: str, password: str) -> None:
            assert (username, password) == ("smtp-user", "smtp-password")

        def send_message(
            self,
            message: Any,
            *,
            from_addr: str,
            to_addrs: list[str],
        ) -> None:
            assert from_addr == "bibmgr@example.test"
            assert to_addrs == ["member@example.test"]
            sent_messages.append(message)

    monkeypatch.setattr("bibmgr_backend.auth.smtplib.SMTP", FakeSmtp)
    mailer = SmtpLoginCodeMailer(
        host="smtp.example",
        port=587,
        sender="bibmgr@example.test",
        username="smtp-user",
        password="smtp-password",
        security=SmtpSecurity.STARTTLS,
    )

    mailer.send_login_code(
        recipient="member@example.test",
        code="12345678",
        expires_in_minutes=10,
    )

    assert ehlo_count == 2
    assert len(sent_messages) == 1
    assert sent_messages[0]["To"] == "member@example.test"
    content = sent_messages[0].get_content()
    assert sent_messages[0]["Subject"] == "BibMgR login code"
    assert "Use the following code to sign in to BibMgR:" in content
    assert "12345678" in content
    assert "expires in 10 minutes" in content
    assert "If you did not request this code" in content
    assert "ログイン" not in content


def test_implicit_tls_mailer_uses_smtp_ssl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: list[Any] = []

    class FakeSmtpSsl:
        def __init__(
            self,
            host: str,
            port: int,
            timeout: int,
            context: ssl.SSLContext,
        ) -> None:
            assert (host, port, timeout) == ("smtp.example", 465, 10)
            assert context.minimum_version is ssl.TLSVersion.TLSv1_2
            assert context.check_hostname
            assert context.verify_mode is ssl.CERT_REQUIRED

        def __enter__(self) -> FakeSmtpSsl:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def login(self, username: str, password: str) -> None:
            assert (username, password) == ("smtp-user", "smtp-password")

        def send_message(
            self,
            message: Any,
            *,
            from_addr: str,
            to_addrs: list[str],
        ) -> None:
            assert from_addr == "bibmgr@example.test"
            assert to_addrs == ["member@example.test"]
            sent_messages.append(message)

    def unexpected_smtp(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("implicit TLS must not use plaintext SMTP")

    monkeypatch.setattr("bibmgr_backend.auth.smtplib.SMTP", unexpected_smtp)
    monkeypatch.setattr(
        "bibmgr_backend.auth.smtplib.SMTP_SSL", FakeSmtpSsl
    )
    mailer = SmtpLoginCodeMailer(
        host="smtp.example",
        port=465,
        sender="bibmgr@example.test",
        username="smtp-user",
        password="smtp-password",
        security=SmtpSecurity.IMPLICIT_TLS,
    )

    mailer.send_login_code(
        recipient="member@example.test",
        code="12345678",
        expires_in_minutes=10,
    )

    assert len(sent_messages) == 1


def test_plain_mailer_uses_an_unauthenticated_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: list[Any] = []

    class FakeSmtp:
        def __init__(
            self, host: str, port: int, timeout: int
        ) -> None:
            assert (host, port, timeout) == ("relay.example", 25, 10)

        def __enter__(self) -> FakeSmtp:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def send_message(
            self,
            message: Any,
            *,
            from_addr: str,
            to_addrs: list[str],
        ) -> None:
            assert from_addr == "bibmgr@example.test"
            assert to_addrs == ["member@example.test"]
            sent_messages.append(message)

    def unexpected_smtp_ssl(
        *_args: object, **_kwargs: object
    ) -> None:
        raise AssertionError("plain SMTP must not use SMTP_SSL")

    monkeypatch.setattr("bibmgr_backend.auth.smtplib.SMTP", FakeSmtp)
    monkeypatch.setattr(
        "bibmgr_backend.auth.smtplib.SMTP_SSL", unexpected_smtp_ssl
    )
    mailer = SmtpLoginCodeMailer(
        host="relay.example",
        port=25,
        sender="bibmgr@example.test",
        security=SmtpSecurity.PLAIN,
    )

    mailer.send_login_code(
        recipient="member@example.test",
        code="12345678",
        expires_in_minutes=10,
    )

    assert len(sent_messages) == 1
