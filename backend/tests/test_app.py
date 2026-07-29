from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bibmgr_backend.app import create_app
from bibmgr_backend.auth import AuthenticationManager
from bibmgr_backend.db_models import Base
from bibmgr_backend.native import NativeCallError


class RecordingEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def analyze(self, source: str, profile: str, mode: str) -> dict[str, Any]:
        self.calls.append(("analyze", (source, profile, mode)))
        return {
            "schema_version": "1",
            "source_revision": "sha256:" + "0" * 64,
            "diagnostics": [],
            "available_fixes": [],
        }

    def apply_fixes(
        self, source: str, source_revision: str, fix_ids: list[str], profile: str
    ) -> dict[str, Any]:
        self.calls.append(
            ("apply_fixes", (source, source_revision, fix_ids, profile))
        )
        return {
            "schema_version": "1",
            "source": source,
            "source_revision": "sha256:" + "1" * 64,
            "applied_fix_ids": fix_ids,
        }

    def validate_for_registration(
        self, source: str, policy: str
    ) -> dict[str, Any]:
        self.calls.append(("validate", (source, policy)))
        return {
            "schema_version": "1",
            "accepted": True,
            "source_revision": "sha256:" + "2" * 64,
            "diagnostics": [],
        }

    def canonicalize_for_storage(
        self, source: str, policy: str
    ) -> dict[str, Any]:
        self.calls.append(("canonicalize", (source, policy)))
        return {
            "schema_version": "1",
            "accepted": True,
            "source": source,
            "source_revision": "sha256:" + "3" * 64,
            "diagnostics": [],
        }

    def export_profiles(self) -> dict[str, Any]:
        self.calls.append(("export_profiles", ()))
        return {
            "schema_version": "1",
            "profiles": [
                {
                    "id": "modern",
                    "display_name": "Modern BibTeX",
                    "description": "Modern BibTeX output.",
                    "validation_profile": "modern",
                    "preprint_representation": "misc-eprint",
                },
                {
                    "id": "laboratory",
                    "display_name": "Laboratory",
                    "description": "Laboratory repository output.",
                    "validation_profile": "laboratory",
                    "preprint_representation": "misc-eprint",
                },
            ],
        }

    def export_source(self, source: str, profile: str) -> dict[str, Any]:
        self.calls.append(("export", (source, profile)))
        return {"schema_version": "1", "source": source, "profile": profile}


class CapturingMailer:
    def __init__(self) -> None:
        self.code = ""

    def send_login_code(
        self,
        *,
        recipient: str,
        code: str,
        expires_in_minutes: int,
    ) -> None:
        self.code = code


def client_and_engine(
    engine: RecordingEngine | None = None,
    *,
    authenticated: bool = True,
) -> tuple[TestClient, RecordingEngine]:
    selected_engine = engine or RecordingEngine()
    database = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(database)
    sessions = sessionmaker(
        bind=database,
        class_=Session,
        expire_on_commit=False,
    )
    mailer = CapturingMailer()
    authentication = AuthenticationManager(
        mailer=mailer,
        secret=b"backend-transport-test-secret",
        code_generator=lambda: "12345678",
        session_token_generator=lambda: "backend-transport-session",
        secure_cookie=False,
    )
    client = TestClient(
        create_app(
            selected_engine,
            session_factory=sessions,
            authentication=authentication,
        )
    )
    if authenticated:
        email = "transport@ai.cs.ehime-u.ac.jp"
        assert client.post(
            "/auth/email/start", json={"email": email}
        ).status_code == 202
        verified = client.post(
            "/auth/email/verify",
            json={"email": email, "code": mailer.code},
        )
        assert verified.status_code == 200
        client.headers["X-CSRF-Token"] = verified.json()["csrfToken"]
    return client, selected_engine


def test_analyze_passes_source_profile_and_mode_unchanged() -> None:
    client, engine = client_and_engine()
    source = "@article{key,\n  title = {日本語}\n}"

    response = client.post(
        "/bibtex/analyze",
        json={"source": source, "profile": "acl", "mode": "tolerant"},
    )

    assert response.status_code == 200
    assert response.json()["schema_version"] == "1"
    assert engine.calls == [("analyze", (source, "acl", "tolerant"))]


def test_apply_fix_ids_are_forwarded_without_interpretation() -> None:
    client, engine = client_and_engine()

    response = client.post(
        "/bibtex/fixes/apply",
        json={
            "source": "@misc{key}",
            "source_revision": "sha256:" + "0" * 64,
            "fix_ids": ["LAB-ENTRY-003:0", "BIB-SYNTAX-004:0"],
            "profile": "laboratory",
        },
    )

    assert response.status_code == 200
    assert response.json()["applied_fix_ids"] == [
        "LAB-ENTRY-003:0",
        "BIB-SYNTAX-004:0",
    ]
    assert engine.calls == [
        (
            "apply_fixes",
            (
                "@misc{key}",
                "sha256:" + "0" * 64,
                ["LAB-ENTRY-003:0", "BIB-SYNTAX-004:0"],
                "laboratory",
            ),
        )
    ]


def test_apply_requires_the_analyzed_source_revision() -> None:
    client, engine = client_and_engine()

    response = client.post(
        "/bibtex/fixes/apply",
        json={"source": "@misc{key}", "fix_ids": ["BIB-SYNTAX-004:0"]},
    )

    assert response.status_code == 422
    assert response.json() == {
        "schema_version": "1",
        "error": {
            "code": "invalid_request",
            "message": "Request validation failed.",
        },
    }
    assert engine.calls == []


def test_registration_uses_the_archive_policy_by_default() -> None:
    client, engine = client_and_engine()

    response = client.post(
        "/bibtex/registration/validate",
        json={"source": ""},
    )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert engine.calls == [("validate", ("", "archive"))]


def test_storage_canonicalization_uses_the_native_decision() -> None:
    client, engine = client_and_engine()
    source = "@misc{key, Title={T}}"

    response = client.post(
        "/bibtex/registration/canonicalize",
        json={"source": source, "policy": "laboratory"},
    )

    assert response.status_code == 200
    assert response.json()["source"] == source
    assert engine.calls == [("canonicalize", (source, "laboratory"))]


def test_export_is_a_separate_native_operation() -> None:
    client, engine = client_and_engine()

    response = client.post(
        "/bibtex/export",
        json={"source": "@misc{key}", "profile": "classical-bst"},
    )

    assert response.status_code == 200
    assert response.json()["profile"] == "classical-bst"
    assert engine.calls == [("export", ("@misc{key}", "classical-bst"))]


def test_export_profile_catalog_is_forwarded_without_adapter_rules() -> None:
    client, engine = client_and_engine()

    response = client.get("/bibtex/export/profiles")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1",
        "profiles": [
            {
                "id": "modern",
                "display_name": "Modern BibTeX",
                "description": "Modern BibTeX output.",
                "validation_profile": "modern",
                "preprint_representation": "misc-eprint",
            },
            {
                "id": "laboratory",
                "display_name": "Laboratory",
                "description": "Laboratory repository output.",
                "validation_profile": "laboratory",
                "preprint_representation": "misc-eprint",
            },
        ],
    }
    assert engine.calls == [("export_profiles", ())]


def test_unknown_request_fields_are_rejected() -> None:
    client, engine = client_and_engine()

    response = client.post(
        "/bibtex/analyze",
        json={"source": "", "mode": "tolerant", "run_python_rule": True},
    )

    assert response.status_code == 422
    assert response.json() == {
        "schema_version": "1",
        "error": {
            "code": "invalid_request",
            "message": "Request validation failed.",
        },
    }
    assert engine.calls == []


def test_openapi_advertises_versioned_request_validation_errors() -> None:
    schema = create_app(RecordingEngine()).openapi()

    response_schema = schema["paths"]["/bibtex/analyze"]["post"]["responses"][
        "422"
    ]["content"]["application/json"]["schema"]

    assert response_schema == {"$ref": "#/components/schemas/ErrorResponse"}
    assert schema["components"]["schemas"]["ErrorResponse"]["required"] == [
        "schema_version",
        "error",
    ]
    assert "401" in schema["paths"]["/bibtex/analyze"]["post"]["responses"]


def test_bibtex_operations_require_authentication() -> None:
    client, engine = client_and_engine(authenticated=False)

    response = client.post(
        "/bibtex/analyze",
        json={"source": "@misc{key}", "mode": "tolerant"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert engine.calls == []
    assert client.get("/bibtex/export/profiles").status_code == 401
    assert client.get("/healthz").status_code == 200


class FailingEngine(RecordingEngine):
    def analyze(self, source: str, profile: str, mode: str) -> dict[str, Any]:
        raise NativeCallError("configuration_error", "unknown profile", 400)


def test_native_errors_use_the_versioned_error_dto() -> None:
    client, _engine = client_and_engine(FailingEngine())

    response = client.post("/bibtex/analyze", json={"source": ""})

    assert response.status_code == 400
    assert response.json() == {
        "schema_version": "1",
        "error": {"code": "configuration_error", "message": "unknown profile"},
    }


def test_request_ids_and_metrics_use_normalized_routes() -> None:
    client, _engine = client_and_engine()

    response = client.get("/healthz", headers={"X-Request-ID": "test-request-1"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-1"
    metrics = client.get("/metrics").text
    assert (
        'bibmgr_http_requests_total{method="GET",route="/healthz",status="200"} 1'
        in metrics
    )
    assert (
        'bibmgr_http_request_duration_seconds_count'
        '{method="GET",route="/healthz"} 1'
        in metrics
    )


def test_invalid_request_id_is_replaced() -> None:
    client, _engine = client_and_engine()

    response = client.get("/healthz", headers={"X-Request-ID": "not valid"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "not valid"
