from __future__ import annotations

from hashlib import sha256
import uuid
from typing import Any

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bibmgr_backend.app import create_app
from bibmgr_backend.auth import AuthenticationManager
from bibmgr_backend.db_models import (
    Base,
    ReferenceAuditEvent,
    ReferenceContributor,
    ReferenceHistoryHead,
    ReferenceIdentifier,
    ReferenceRecord,
    UserRecord,
)
from bibmgr_backend.native import NativeEngine


def revision(source: str) -> str:
    return f"sha256:{sha256(source.encode('utf-8')).hexdigest()}"


def sourced(value: Any) -> dict[str, Any]:
    return {
        "value": value,
        "origins": [],
        "status": "parsed",
        "confidence": "high",
    }


def person(given: str, family: str) -> dict[str, Any]:
    return sourced(
        {
            "raw": f"{family}, {given}",
            "given": [given],
            "family": [family],
            "prefix": [],
            "suffix": [],
            "literal": None,
        }
    )


def semantic_record(
    *,
    key: str,
    title: str,
    authors: list[tuple[str, str]],
    doi: str | None = None,
    start: int = 0,
    end: int = 1,
) -> dict[str, Any]:
    return {
        "citation_key": sourced(key),
        "entry_type": sourced("article"),
        "work_type": sourced("journal_article"),
        "title": sourced(title),
        "authors": [person(given, family) for given, family in authors],
        "editors": [],
        "date": sourced(
            {"raw": "2024", "year": 2024, "month": None, "day": None}
        ),
        "venue": sourced(
            {
                "raw": "TACL",
                "venue_id": "tacl",
                "full_name": (
                    "Transactions of the Association for Computational "
                    "Linguistics"
                ),
                "short_name": "TACL",
                "kind": "journal",
            }
        ),
        "preprint": None,
        "identifiers": {
            "dois": [sourced(doi)] if doi else [],
            "arxiv": [],
            "isbns": [],
            "issns": [],
            "other": [],
        },
        "urls": [],
        "extra_fields": [],
        "unresolved_values": [],
        "ambiguities": [],
        "conflicts": [],
        "origins": [
            {
                "source_id": "source:0",
                "range": {"start": start, "end": end},
                "kind": "entry",
                "field_name": None,
            }
        ],
    }


class RegistrationEngine:
    def __init__(self) -> None:
        self.records_by_source: dict[str, list[dict[str, Any]]] = {}
        self.canonical_sources: dict[str, str] = {}
        self.rejected_sources: set[str] = set()
        self.calls: list[tuple[str, str]] = []
        self.canonicalization_calls: list[tuple[str, str]] = []

    def add(
        self, source: str, records: list[dict[str, Any]]
    ) -> None:
        self.records_by_source[source] = records

    def validate_for_registration(
        self, source: str, policy: str
    ) -> dict[str, Any]:
        self.calls.append((source, policy))
        accepted = source not in self.rejected_sources
        return {
            "schema_version": "1",
            "accepted": accepted,
            "source": source,
            "source_revision": revision(source),
            "diagnostics": (
                []
                if accepted
                else [
                    {
                        "id": "TEST-001:0",
                        "code": "TEST-001",
                        "severity": "error",
                        "blocking": True,
                        "message": "blocked",
                    }
                ]
            ),
            "bibliography": {
                "records": self.records_by_source.get(source, []),
                "diagnostics": [],
            },
            "applied_fix_ids": [],
            "unresolved_semantics": False,
        }

    def canonicalize_for_storage(
        self, source: str, policy: str
    ) -> dict[str, Any]:
        self.canonicalization_calls.append((source, policy))
        canonical_source = self.canonical_sources.get(source, source)
        accepted = source not in self.rejected_sources
        return {
            "schema_version": "1",
            "accepted": accepted,
            "source": canonical_source,
            "source_revision": revision(canonical_source),
            "diagnostics": [],
            "bibliography": {
                "records": self.records_by_source.get(
                    canonical_source,
                    self.records_by_source.get(source, []),
                ),
                "diagnostics": [],
            },
            "applied_fix_ids": [],
            "unresolved_semantics": False,
        }

    def analyze(self, source: str, profile: str, mode: str) -> dict[str, Any]:
        raise AssertionError("not used")

    def apply_fixes(
        self, source: str, source_revision: str, fix_ids: list[str], profile: str
    ) -> dict[str, Any]:
        raise AssertionError("not used")

    def export_profiles(self) -> dict[str, Any]:
        raise AssertionError("not used")

    def export_source(self, source: str, profile: str) -> dict[str, Any]:
        raise AssertionError("not used")


class CapturingMailer:
    def __init__(self) -> None:
        self.codes: dict[str, str] = {}

    def send_login_code(
        self,
        *,
        recipient: str,
        code: str,
        expires_in_minutes: int,
    ) -> None:
        assert expires_in_minutes == 10
        self.codes[recipient] = code


def build_authentication(mailer: CapturingMailer) -> AuthenticationManager:
    return AuthenticationManager(
        mailer=mailer,
        secret=b"reference-api-test-secret",
        code_generator=lambda: "12345678",
        session_token_generator=lambda: f"test-session-{uuid.uuid4()}",
        secure_cookie=False,
    )


def login_test_client(
    client: TestClient,
    mailer: CapturingMailer,
    email: str = "researcher@ai.cs.ehime-u.ac.jp",
) -> None:
    started = client.post("/auth/email/start", json={"email": email})
    assert started.status_code == 202
    verified = client.post(
        "/auth/email/verify",
        json={"email": email, "code": mailer.codes[email]},
    )
    assert verified.status_code == 200
    client.headers["X-CSRF-Token"] = verified.json()["csrfToken"]


def build_test_client() -> tuple[
    TestClient, RegistrationEngine, sessionmaker[Session]
]:
    database = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(database, "connect")
    def enable_foreign_keys(
        connection: Any, _connection_record: Any
    ) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(database)
    sessions = sessionmaker(
        bind=database, class_=Session, expire_on_commit=False
    )
    registration_engine = RegistrationEngine()
    mailer = CapturingMailer()
    client = TestClient(
        create_app(
            registration_engine,
            session_factory=sessions,
            registration_policy="archive",
            authentication=build_authentication(mailer),
        )
    )
    login_test_client(client, mailer)
    return client, registration_engine, sessions


def test_registration_separates_display_title_from_stored_bibtex() -> None:
    client, engine, sessions = build_test_client()
    source = (
        "@inproceedings{gong-etal-2023-diffuseq,\n"
        "  title = {{D}iffu{S}eq-v2: Bridging Text Spaces},\n"
        "}\n"
    )
    engine.add(
        source,
        [
            semantic_record(
                key="gong-etal-2023-diffuseq",
                title="{D}iffu{S}eq-v2: Bridging Text Spaces",
                authors=[],
            )
        ],
    )

    response = client.post(
        "/references",
        json={"bibtex": source, "source": "manual"},
    )

    assert response.status_code == 201
    assert response.json()["reference"]["title"] == (
        "DiffuSeq-v2: Bridging Text Spaces"
    )
    assert response.json()["reference"]["bibtex"] == source
    with sessions() as session:
        record = session.scalar(select(ReferenceRecord))
        assert record is not None
        assert record.title == "DiffuSeq-v2: Bridging Text Spaces"
        assert record.canonical_bibtex == source


def test_register_search_edit_and_delete_reference() -> None:
    client, engine, sessions = build_test_client()
    original = (
        "@article{yamada2024, title = {日本語解析}, "
        "author = {山田, 太郎}, year = {2024}}\n"
    )
    engine.add(
        original,
        [
            semantic_record(
                key="yamada2024",
                title="日本語解析",
                authors=[("太郎", "山田")],
                doi="10.1000/original",
            )
        ],
    )

    registered = client.post(
        "/references",
        json={"bibtex": original, "source": "manual"},
    )

    assert registered.status_code == 201
    payload = registered.json()
    assert payload["reference"] == payload["references"][0]
    assert payload["reference"]["authors"] == ["太郎 山田"]
    assert payload["reference"]["doi"] == "10.1000/original"
    assert payload["reference"]["bibtex"] == original
    reference_id = payload["reference"]["id"]
    original_revision = payload["reference"]["sourceRevision"]
    assert engine.calls == [(original, "archive")]
    assert engine.canonicalization_calls == []

    searched = client.get("/references", params={"query": "山田"})
    assert searched.status_code == 200
    assert [item["id"] for item in searched.json()] == [reference_id]

    loaded = client.get(f"/references/{reference_id}")
    assert loaded.status_code == 200
    assert loaded.json()["title"] == "日本語解析"

    edited = original.replace("日本語解析", "日本語意味解析")
    engine.add(
        edited,
        [
            semantic_record(
                key="yamada2024",
                title="日本語意味解析",
                authors=[("太郎", "山田")],
                doi="10.1000/edited",
            )
        ],
    )

    stale = client.put(
        f"/references/{reference_id}",
        json={
            "bibtex": edited,
            "source_revision": "sha256:" + "0" * 64,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_reference"
    assert (
        stale.json()["error"]["details"]["source_revision"]
        == original_revision
    )

    updated = client.put(
        f"/references/{reference_id}",
        json={
            "bibtex": edited,
            "source_revision": original_revision,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "日本語意味解析"
    assert updated.json()["doi"] == "10.1000/edited"
    assert updated.json()["sourceRevision"] == revision(edited)
    assert updated.json()["bibtex"] == edited
    assert engine.canonicalization_calls == []

    stale_delete = client.delete(
        f"/references/{reference_id}",
        headers={"If-Match": f'"{original_revision}"'},
    )
    assert stale_delete.status_code == 409
    deleted = client.delete(
        f"/references/{reference_id}",
        headers={
            "If-Match": f'"{updated.json()["sourceRevision"]}"'
        },
    )
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get(f"/references/{reference_id}").status_code == 404

    with sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(ReferenceRecord)
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(ReferenceContributor)
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(ReferenceIdentifier)
        ) == 0
        user = session.scalar(select(UserRecord))
        events = list(
            session.scalars(
                select(ReferenceAuditEvent).order_by(
                    ReferenceAuditEvent.occurred_at
                )
            )
        )
        assert user is not None
        assert [event.action for event in events] == [
            "create",
            "update",
            "delete",
        ]
        assert [event.revision for event in events] == [1, 2, 3]
        assert all(event.actor_user_id == user.id for event in events)
        assert events[0].after_data is not None
        assert events[0].after_data["snapshot_version"] == 2
        assert events[0].after_data["submitted_bibtex"] == original
        assert events[0].after_data["canonical_bibtex"] == original
        assert events[0].after_data["contributors"][0][
            "display_name"
        ] == "太郎 山田"
        assert events[1].before_data is not None
        assert events[1].after_data is not None
        assert events[2].before_data is not None
        assert events[2].after_data is None


def test_registration_stores_submitted_bibtex_without_canonicalization() -> None:
    client, engine, sessions = build_test_client()
    submitted = "@article{canonical,Title={Canonical paper}}\n"
    canonical = (
        "@article{canonical,\n"
        "  title = {Canonical paper},\n"
        "}\n"
    )
    submitted_record = semantic_record(
        key="canonical",
        title="Canonical paper",
        authors=[],
        end=len(submitted.rstrip("\n").encode()),
    )
    engine.add(submitted, [submitted_record])
    engine.canonical_sources[submitted] = canonical

    response = client.post(
        "/references",
        json={"bibtex": submitted, "source": "manual"},
    )

    assert response.status_code == 201
    reference = response.json()["reference"]
    assert reference["bibtex"] == submitted
    assert reference["sourceRevision"] == revision(submitted)
    assert engine.canonicalization_calls == []

    with sessions() as session:
        stored = session.scalar(select(ReferenceRecord))
        event_record = session.scalar(select(ReferenceAuditEvent))
        assert stored is not None
        assert stored.canonical_bibtex == submitted
        assert event_record is not None
        assert event_record.after_data is not None
        assert event_record.after_data["submitted_bibtex"] == submitted
        assert event_record.after_data["canonical_bibtex"] == submitted
        assert event_record.after_data["semantic_data"]["title"]["value"] == (
            "Canonical paper"
        )


def test_edit_and_delete_history_can_be_reverted() -> None:
    client, engine, sessions = build_test_client()
    original = "@article{history, title = {Original}}\n"
    edited = "@article{history, title = {Edited}}\n"
    engine.add(
        original,
        [
            semantic_record(
                key="history",
                title="Original",
                authors=[("Taro", "Ehime")],
                doi="10.1000/history",
            )
        ],
    )
    engine.add(
        edited,
        [
            semantic_record(
                key="history",
                title="Edited",
                authors=[],
                doi="10.1000/history",
            )
        ],
    )

    created = client.post(
        "/references",
        json={"bibtex": original, "source": "manual"},
    ).json()["reference"]
    reference_id = created["id"]
    updated = client.put(
        f"/references/{reference_id}",
        json={
            "bibtex": edited,
            "source_revision": created["sourceRevision"],
        },
    )
    assert updated.status_code == 200
    assert client.delete(
        f"/references/{reference_id}",
        headers={
            "If-Match": f'"{updated.json()["sourceRevision"]}"'
        },
    ).status_code == 204

    catalog = client.get("/reference-history")
    assert catalog.status_code == 200
    assert catalog.json()[0] == {
        "referenceId": reference_id,
        "headRevision": 3,
        "exists": False,
        "title": "Edited",
        "latestAction": "delete",
        "updatedAt": catalog.json()[0]["updatedAt"],
    }

    history = client.get(f"/references/{reference_id}/history")
    assert history.status_code == 200
    assert history.json()["headRevision"] == 3
    assert history.json()["exists"] is False
    assert [
        (item["revision"], item["action"], item["restorable"])
        for item in history.json()["revisions"]
    ] == [
        (3, "delete", False),
        (2, "update", True),
        (1, "create", True),
    ]
    created_revision = history.json()["revisions"][-1]
    assert created_revision["submittedBibtex"] == original
    assert created_revision["canonicalBibtex"] == original

    restored = client.post(
        f"/references/{reference_id}/revert",
        json={
            "target_revision": 1,
            "expected_head_revision": 3,
        },
    )
    assert restored.status_code == 200
    assert restored.json()["id"] == reference_id
    assert restored.json()["title"] == "Original"
    assert restored.json()["authors"] == ["Taro Ehime"]
    assert restored.json()["doi"] == "10.1000/history"

    restored_history = client.get(
        f"/references/{reference_id}/history"
    ).json()
    assert restored_history["headRevision"] == 4
    assert restored_history["exists"] is True
    assert restored_history["revisions"][0]["action"] == "restore"
    assert (
        restored_history["revisions"][0]["restoredFromRevision"]
        == 1
    )

    stale = client.post(
        f"/references/{reference_id}/revert",
        json={
            "target_revision": 2,
            "expected_head_revision": 3,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_reference_history"
    assert stale.json()["error"]["details"]["head_revision"] == 4

    tombstone = client.post(
        f"/references/{reference_id}/revert",
        json={
            "target_revision": 3,
            "expected_head_revision": 4,
        },
    )
    assert tombstone.status_code == 422
    assert (
        tombstone.json()["error"]["code"]
        == "reference_revision_not_restorable"
    )

    with sessions() as session:
        events = list(
            session.scalars(
                select(ReferenceAuditEvent)
                .where(
                    ReferenceAuditEvent.reference_id
                    == uuid.UUID(reference_id)
                )
                .order_by(ReferenceAuditEvent.revision)
            )
        )
        assert [event.revision for event in events] == [1, 2, 3, 4]
        assert events[-1].restored_from_revision == 1


def test_restore_rechecks_strong_identifier_uniqueness() -> None:
    client, engine, _sessions = build_test_client()
    original = "@article{original, title = {Original}}\n"
    replacement = "@article{replacement, title = {Replacement}}\n"
    engine.add(
        original,
        [
            semantic_record(
                key="original",
                title="Original",
                authors=[],
                doi="10.1000/reused-after-delete",
            )
        ],
    )
    engine.add(
        replacement,
        [
            semantic_record(
                key="replacement",
                title="Replacement",
                authors=[],
                doi="10.1000/reused-after-delete",
            )
        ],
    )

    original_reference = client.post(
        "/references",
        json={"bibtex": original, "source": "manual"},
    ).json()["reference"]
    original_id = original_reference["id"]
    assert client.delete(
        f"/references/{original_id}",
        headers={
            "If-Match": f'"{original_reference["sourceRevision"]}"'
        },
    ).status_code == 204
    assert client.post(
        "/references",
        json={"bibtex": replacement, "source": "manual"},
    ).status_code == 201

    conflict = client.post(
        f"/references/{original_id}/revert",
        json={
            "target_revision": 1,
            "expected_head_revision": 2,
        },
    )

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "duplicate_reference"
    history = client.get(f"/references/{original_id}/history").json()
    assert history["headRevision"] == 2
    assert history["exists"] is False


def test_duplicate_doi_is_rejected_without_partial_registration() -> None:
    client, engine, _sessions = build_test_client()
    first = "@article{first, title = {First}}\n"
    duplicate = "@article{duplicate, title = {Duplicate}}\n"
    engine.add(
        first,
        [
            semantic_record(
                key="first",
                title="First",
                authors=[],
                doi="10.1000/shared",
            )
        ],
    )
    engine.add(
        duplicate,
        [
            semantic_record(
                key="duplicate",
                title="Duplicate",
                authors=[],
                doi="10.1000/shared",
            )
        ],
    )

    assert client.post(
        "/references", json={"bibtex": first, "source": "manual"}
    ).status_code == 201
    rejected = client.post(
        "/references", json={"bibtex": duplicate, "source": "manual"}
    )

    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "duplicate_reference"
    assert len(client.get("/references").json()) == 1


def test_multiple_utf8_entries_are_split_and_saved_atomically() -> None:
    client, engine, _sessions = build_test_client()
    first = "@article{one, title = {第一の論文}}\n"
    second = "@article{two, title = {Second paper}}\n"
    source = f"{first}\n{second}"
    second_start = len(f"{first}\n".encode())
    engine.add(
        source,
        [
            semantic_record(
                key="one",
                title="第一の論文",
                authors=[],
                start=0,
                end=len(first.rstrip("\n").encode()),
            ),
            semantic_record(
                key="two",
                title="Second paper",
                authors=[],
                start=second_start,
                end=len(source.rstrip("\n").encode()),
            ),
        ],
    )

    response = client.post(
        "/references", json={"bibtex": source, "source": "file"}
    )

    assert response.status_code == 201
    references = response.json()["references"]
    assert [item["title"] for item in references] == [
        "第一の論文",
        "Second paper",
    ]
    assert references[0]["bibtex"] == first.rstrip("\n")
    assert references[1]["bibtex"] == second.rstrip("\n")


def test_structured_search_page_returns_total_and_filters() -> None:
    client, engine, _sessions = build_test_client()
    first = "@article{one, title = {First}}\n"
    second = "@inproceedings{two, title = {Second}}\n"
    engine.add(
        first,
        [
            semantic_record(
                key="one",
                title="First",
                authors=[("Ada", "Lovelace")],
            )
        ],
    )
    second_record = semantic_record(
        key="two",
        title="Second",
        authors=[("Grace", "Hopper")],
    )
    second_record["entry_type"] = sourced("inproceedings")
    engine.add(second, [second_record])
    client.post(
        "/references", json={"bibtex": first, "source": "manual"}
    )
    client.post(
        "/references", json={"bibtex": second, "source": "manual"}
    )

    page = client.get(
        "/references/page",
        params={
            "author": "Grace",
            "entry_type": "inproceedings",
            "limit": 1,
            "offset": 0,
            "sort": "title_asc",
        },
    )

    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert [item["title"] for item in page.json()["items"]] == ["Second"]

    citation_key_page = client.get(
        "/references/page",
        params={"identifier": "two"},
    )

    assert citation_key_page.status_code == 200
    assert citation_key_page.json()["total"] == 1
    assert [
        item["title"] for item in citation_key_page.json()["items"]
    ] == ["Second"]


def test_history_page_total_excludes_heads_without_events() -> None:
    client, _engine, sessions = build_test_client()
    with sessions() as session:
        session.add(
            ReferenceHistoryHead(
                reference_id=uuid.uuid4(),
                latest_revision=0,
            )
        )
        session.commit()

    page = client.get("/reference-history/page")

    assert page.status_code == 200
    assert page.json()["items"] == []
    assert page.json()["total"] == 0


def test_citation_contexts_are_audited_and_visible() -> None:
    client, engine, _sessions = build_test_client()
    source = "@article{contexts, title = {Citation contexts}}\n"
    engine.add(
        source,
        [
            semantic_record(
                key="contexts",
                title="Citation contexts",
                authors=[],
            )
        ],
    )

    created = client.post(
        "/references",
        json={
            "bibtex": source,
            "source": "manual",
            "citation_contexts": [
                {
                    "source_paper_title": "Citing paper",
                    "source_file_name": "paper.pdf",
                    "context": "Citation contexts are useful.",
                }
            ],
        },
    )
    assert created.status_code == 201
    reference = created.json()["reference"]
    assert reference["citationContexts"][0]["context"] == (
        "Citation contexts are useful."
    )

    augmented = client.post(
        f"/references/{reference['id']}/citation-contexts",
        json={
            "contexts": [
                {
                    "source_paper_title": "Another paper",
                    "context": "A second citation.",
                }
            ]
        },
    )
    assert augmented.status_code == 200
    assert len(augmented.json()["citationContexts"]) == 2
    history = client.get(
        f"/references/{reference['id']}/history"
    ).json()
    assert history["headRevision"] == 2
    assert history["revisions"][0]["action"] == "context"


def test_native_rejection_returns_diagnostics_and_writes_nothing() -> None:
    client, engine, _sessions = build_test_client()
    source = "@article{blocked, title = {Blocked}}\n"
    engine.rejected_sources.add(source)

    response = client.post(
        "/references", json={"bibtex": source, "source": "manual"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "registration_rejected"
    assert response.json()["error"]["details"]["diagnostics"][0][
        "blocking"
    ] is True
    assert client.get("/references").json() == []


def test_reference_id_and_pagination_parameters_are_validated() -> None:
    client, _engine, _sessions = build_test_client()

    assert client.get("/references/not-a-uuid").status_code == 422
    assert client.get("/references", params={"limit": 101}).status_code == 422
    assert client.get(
        f"/references/{uuid.uuid4()}"
    ).status_code == 404


def test_persistence_policy_cannot_be_overridden_by_the_client() -> None:
    client, engine, _sessions = build_test_client()

    response = client.post(
        "/references",
        json={
            "bibtex": "@article{key}",
            "source": "manual",
            "policy": "modern",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert engine.calls == []


def test_real_native_registration_dto_maps_to_relational_storage() -> None:
    native_module = pytest.importorskip("bibmgr_native")
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
    client = TestClient(
        create_app(
            NativeEngine(native_module),
            session_factory=sessions,
            registration_policy="archive",
            authentication=build_authentication(mailer),
        )
    )
    login_test_client(client, mailer)
    source = (
        "@article{yamada2024, author = {山田, 太郎}, "
        "title = {日本語解析}, journal = {TACL}, year = {2024}, "
        "doi = {10.1000/native-example},}\n"
    )

    response = client.post(
        "/references",
        json={"bibtex": source, "source": "manual"},
    )

    assert response.status_code == 201
    reference = response.json()["reference"]
    assert reference["title"] == "日本語解析"
    assert reference["authors"] == ["太郎 山田"]
    assert reference["doi"] == "10.1000/native-example"
    assert reference["bibtex"] == source

    with sessions() as session:
        event_record = session.scalar(select(ReferenceAuditEvent))
        assert event_record is not None
        assert event_record.after_data is not None
        assert event_record.after_data["submitted_bibtex"] == source
        assert event_record.after_data["canonical_bibtex"] == source
