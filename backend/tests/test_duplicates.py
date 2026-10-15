from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
import pytest

from bibmgr_backend.app import create_app
from bibmgr_backend.db_models import ReferenceComparison, ReferenceComparisonKey, ReferenceRecord
from bibmgr_backend.native import NativeEngine, NativeCallError
from test_references_api import build_test_client, CapturingMailer, build_authentication


def client_for(policy=None):
    authenticated_client, _, sessions = build_test_client()
    mailer = CapturingMailer()
    client = TestClient(create_app(NativeEngine(), session_factory=sessions,
                                  duplicate_policy=policy or {}, authentication=build_authentication(mailer)))
    client.cookies.update(authenticated_client.cookies)
    client.headers.update(authenticated_client.headers)
    return client, sessions


def entry(key, title="A Study", extra=""):
    return f"@article{{{key},title={{{title}}},author={{Doe, Jane}},journal={{TACL}},year={{2024}},pages={{1--9}}{extra}}}"


def register(client, source, token=None):
    return client.post("/references", json={"bibtex": source, "source": "manual", "duplicate_confirmation": token})


def test_default_warnings_do_not_block_and_key_collision_is_reported():
    client, _ = client_for()
    first = register(client, entry("same")).json()["reference"]
    response = register(client, entry("same", "Other study"))
    assert response.status_code == 201, response.text
    finding = response.json()["duplicate_warnings"][0]
    assert finding["comparison"]["kind"] == "citation_key"
    assert finding["action"] == "warn"
    assert finding["reference_id"] == first["id"]
    response = register(client, entry("different"))
    assert response.status_code == 201, response.text
    assert response.json()["duplicate_warnings"][0]["comparison"]["kind"] == "corroborated_title"


def test_confirm_is_bound_to_input_policy_and_current_candidate_revision():
    client, _ = client_for({"corroborated_title": "confirm", "title": "confirm"})
    first = register(client, entry("original")).json()["reference"]
    source = entry("new")
    response = register(client, source)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "duplicate_confirmation_required"
    token = response.json()["error"]["details"]["confirmation_token"]
    assert len(client.get("/references").json()) == 1
    assert register(client, source + "\n", token).status_code == 409
    updated = client.put(f'/references/{first["id"]}', json={"bibtex": entry("original", extra=",note={Changed}"), "source_revision": first["sourceRevision"]})
    assert updated.status_code == 200, updated.text
    stale = register(client, source, token)
    assert stale.status_code == 409
    new_token = stale.json()["error"]["details"]["confirmation_token"]
    assert new_token != token
    assert register(client, source, new_token).status_code == 201


def test_strong_identifiers_cannot_be_bypassed_by_confirmation_and_versions_are_policy_driven():
    client, _ = client_for({"arxiv_family": "reject"})
    first = entry("a", extra=",doi={10.1000/example},eprint={2302.13971v1},archivePrefix={arXiv}")
    assert register(client, first).status_code == 201
    for extra in (",doi={https://doi.org/10.1000/EXAMPLE}", ",eprint={2302.13971v2},archivePrefix={arXiv}"):
        response = register(client, entry("b", "Changed title", extra), "0" * 64)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["details"]["confirmation_token"] is None
    assert len(client.get("/references").json()) == 1


def test_same_title_with_missing_or_conflicting_metadata_requires_review_not_identity():
    client, _ = client_for({"title": "confirm", "corroborated_title": "reject"})
    assert register(client, entry("a")).status_code == 201
    for sample in ("@misc{b,title={A Study}}", entry("b").replace("2024", "2025")):
        response = register(client, sample)
        assert response.status_code == 409
        details = response.json()["error"]["details"]
        assert details["duplicates"][0]["comparison"]["kind"] == "title"
        assert details["confirmation_token"]


def test_batch_is_atomic_and_compares_entries_to_each_other():
    client, _ = client_for({"corroborated_title": "confirm"})
    source = entry("a") + "\n" + entry("b")
    response = register(client, source)
    assert response.status_code == 409, response.text
    assert client.get("/references").json() == []
    details = response.json()["error"]["details"]
    assert details["duplicates"][0]["existing"] is False
    assert len(register(client, source, details["confirmation_token"]).json()["references"]) == 2


def test_update_and_restore_apply_policy_and_exclude_self():
    client, _ = client_for({"corroborated_title": "confirm"})
    original = register(client, entry("a")).json()["reference"]
    response = client.put(f'/references/{original["id"]}', json={"bibtex": entry("a", "Renamed"), "source_revision": original["sourceRevision"]})
    assert response.status_code == 200, response.text
    replacement = register(client, entry("b")).json()["reference"]
    request = {"target_revision": 1, "expected_head_revision": 2}
    response = client.post(f'/references/{original["id"]}/revert', json=request)
    assert response.status_code == 409, response.text
    details = response.json()["error"]["details"]
    assert details["duplicates"][0]["reference_id"] == replacement["id"]
    response = client.post(f'/references/{original["id"]}/revert', json={**request, "duplicate_confirmation": details["confirmation_token"]})
    assert response.status_code == 200, response.text


def test_comparison_index_backfills_existing_records_without_modifying_sources():
    client, sessions = client_for({"corroborated_title": "reject"})
    first = register(client, entry("a")).json()["reference"]
    with sessions.begin() as session:
        session.execute(delete(ReferenceComparisonKey))
        session.execute(delete(ReferenceComparison))
    response = register(client, entry("b"))
    assert response.status_code == 409, response.text
    assert client.get(f'/references/{first["id"]}').json()["bibtex"] == first["bibtex"]
    # Successful write persists the rebuild; failed requests are atomic.
    assert register(client, entry("c", "Unrelated")).status_code == 201
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceComparison)) >= 1
        assert session.scalar(select(func.count()).select_from(ReferenceRecord)) == 2


def test_unknown_policy_fields_fail_closed(monkeypatch, tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"typo": "ignore"}))
    monkeypatch.setenv("BIBMGR_DUPLICATE_POLICY_FILE", str(path))
    from bibmgr_backend.duplicates import DuplicateCheck
    with pytest.raises(NativeCallError, match="unknown field"):
        DuplicateCheck()


@pytest.mark.parametrize("policy", [[], {"identifier": "warn"}, {"title": "typo"}])
def test_invalid_server_policy_is_rejected_at_startup(policy):
    from bibmgr_backend.duplicates import DuplicateCheck
    with pytest.raises((ValueError, NativeCallError)):
        DuplicateCheck(policy)
