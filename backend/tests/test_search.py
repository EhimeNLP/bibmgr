from __future__ import annotations

from unittest.mock import patch
import uuid

import pytest
from sqlalchemy import select

from bibmgr_backend.db_models import (
    ReferenceSearchState,
    UserRecord,
)
from bibmgr_backend.library import ReferenceLibrary
from bibmgr_backend.native import NativeCallError
from bibmgr_backend.search import ReferenceSearch
from test_references_api import build_test_client, semantic_record


def register(client, engine, key, title, authors=None):
    source = f"@article{{{key}, title = {{{title}}}}}\n"
    engine.add(
        source, [semantic_record(key=key, title=title, authors=authors or [])]
    )
    result = client.post(
        "/references", json={"bibtex": source, "source": "manual"}
    )
    assert result.status_code == 201
    return result.json()["reference"]


def test_api_search_ranks_and_filters_before_pagination() -> None:
    client, engine, _sessions = build_test_client()
    relevant = register(
        client,
        engine,
        "vaswani",
        "Attention Is All You Need",
        [("Ashish", "Vaswani")],
    )
    register(client, engine, "newer", "Attention to unrelated details")
    result = client.get(
        "/references/page", params={"query": "attention is all you need"}
    )
    assert result.status_code == 200
    assert result.json()["items"][0]["id"] == relevant["id"]
    result = client.get(
        "/references/page",
        params={
            "query": "Vaswani atention",
            "author": "Vasw",
            "venue": "TACL",
            "identifier": "vas",
            "year": 2024,
            "entry_type": "article",
            "limit": 1,
        },
    )
    assert result.status_code == 200
    assert result.json()["total"] == 1
    assert result.json()["items"][0]["id"] == relevant["id"]
    result = client.get(
        "/references/page",
        params={"query": "attention", "limit": 1, "offset": 2},
    )
    assert result.json()["total"] == 2
    assert result.json()["items"] == []
    register(
        client, engine, "ja", "自然言語処理とＢＥＲＴ", [("太郎", "山田")]
    )
    result = client.get("/references/page", params={"query": "山田 bert"})
    assert [item["bibtexKey"] for item in result.json()["items"]] == ["ja"]
    for query in [
        "しぜんげんごしょり",
        "しぜんげごしょり",
        "やまだたろう BERT",
        '"しぜんげんごしょりとBERT"',
    ]:
        result = client.get(
            "/references/page",
            params={"query": query, "year": 2024, "limit": 1},
        )
        assert result.status_code == 200
        assert result.json()["total"] == 1, query
        assert [item["bibtexKey"] for item in result.json()["items"]] == [
            "ja"
        ], query
        beyond_page = client.get(
            "/references/page",
            params={"query": query, "year": 2024, "limit": 1, "offset": 1},
        )
        assert beyond_page.json()["total"] == 1
        assert beyond_page.json()["items"] == []


def test_independent_indexes_follow_edits_deletion_and_restoration() -> None:
    client, engine, sessions = build_test_client()
    first = register(client, engine, "paper", "Neural retrieval")
    indexes = [ReferenceSearch(), ReferenceSearch()]

    def search(index, query):
        with sessions() as session:
            return index.search(
                session, query=query, limit=10, offset=0, sort="relevance"
            )

    for index in indexes:
        assert search(index, "neural")[0] == [uuid.UUID(first["id"])]
    replacement = "@article{paper, title = {Statistical translation}}\n"
    engine.add(
        replacement,
        [
            semantic_record(
                key="paper", title="Statistical translation", authors=[]
            )
        ],
    )
    updated = client.put(
        f"/references/{first['id']}",
        json={
            "bibtex": replacement,
            "source_revision": first["sourceRevision"],
        },
    )
    assert updated.status_code == 200
    for index in indexes:
        assert search(index, "neural")[1] == 0
        assert search(index, "statistical")[1] == 1
    deleted = client.delete(
        f"/references/{first['id']}",
        headers={"If-Match": f'"{updated.json()["sourceRevision"]}"'},
    )
    assert deleted.status_code == 204
    for index in indexes:
        assert search(index, "statistical")[1] == 0
    restored = client.post(
        f"/references/{first['id']}/revert",
        json={
            "target_revision": 1,
            "expected_head_revision": 3,
        },
    )
    assert restored.status_code == 200
    for index in indexes:
        assert search(index, "neural")[0] == [uuid.UUID(first["id"])]


def test_api_exposes_correction_and_original_spelling_mode() -> None:
    client, engine, _sessions = build_test_client()
    for key in ["one", "two", "three"]:
        register(client, engine, key, "Machine learning")
    params = {"query": "machne learning", "year": 2024, "limit": 1}
    for offset in [0, 1, 3]:
        response = client.get(
            "/references/page", params={**params, "offset": offset}
        )
        assert response.status_code == 200
        page = response.json()
        assert page["total"] == 3
        assert len(page["items"]) == (0 if offset == 3 else 1)
        assert page["correction"] == {
            "original_query": "machne learning",
            "corrected_query": "machine learning",
        }
    original = client.get(
        "/references/page", params={**params, "search_mode": "original"}
    ).json()
    assert original["items"] == []
    assert original["total"] == 0
    assert original["correction"] is None
    typo = register(client, engine, "typo", "Machne learning")
    original = client.get(
        "/references/page", params={**params, "search_mode": "original"}
    ).json()
    assert [item["id"] for item in original["items"]] == [typo["id"]]
    assert client.get("/references/page").json()["correction"] is None
    assert client.get(
        "/references/page", params={"search_mode": "unknown"}
    ).status_code == 422


def test_api_correction_uses_japanese_readings() -> None:
    client, engine, _sessions = build_test_client()
    reference = register(client, engine, "ja", "自然言語処理のための手法")
    params = {"query": "しぜんげごしょり"}
    page = client.get("/references/page", params=params).json()
    assert [item["id"] for item in page["items"]] == [reference["id"]]
    assert page["correction"] == {
        "original_query": "しぜんげごしょり",
        "corrected_query": "しぜんげんごしょり",
    }
    page = client.get(
        "/references/page", params={**params, "search_mode": "original"}
    ).json()
    assert page["total"] == 0
    assert page["correction"] is None


def test_rollback_does_not_advance_generation_or_publish_documents() -> None:
    client, engine, sessions = build_test_client()
    register(client, engine, "retained", "Retained paper")
    index = ReferenceSearch()
    with sessions() as session:
        index.search(session, query="retained", limit=10)
        generation = session.scalar(select(ReferenceSearchState.generation))
    source = "@article{rolledback, title = {Rolledback paper}}\n"
    engine.add(
        source,
        [
            semantic_record(
                key="rolledback", title="Rolledback paper", authors=[]
            )
        ],
    )
    with sessions() as session:
        user = session.scalar(select(UserRecord))
        ReferenceLibrary(engine).register(
            session,
            bibtex=source,
            source="manual",
            policy="archive",
            actor_user_id=user.id,
        )
        session.rollback()
    with sessions() as session:
        assert (
            session.scalar(select(ReferenceSearchState.generation))
            == generation
        )
        assert index.search(session, query="rolledback", limit=10)[1] == 0


def test_warm_search_skips_reindexing_and_recovers_after_index_failure() -> (
    None
):
    client, engine, sessions = build_test_client()
    register(client, engine, "old", "Original paper")
    index = ReferenceSearch()
    with sessions() as session:
        index.search(session, query="original", limit=10)
    native = index._index
    with patch.object(
        native, "apply", side_effect=AssertionError("warm search reindexed")
    ):
        with sessions() as session:
            assert index.search(session, query="original", limit=10)[1] == 1
    register(client, engine, "new", "Additional paper")
    with patch.object(
        native,
        "apply",
        side_effect=NativeCallError("search_unavailable", "test", 503),
    ):
        with sessions() as session, pytest.raises(NativeCallError):
            index.search(session, query="additional", limit=10)
    with sessions() as session:
        assert index.search(session, query="additional", limit=10)[1] == 1
        assert index.search(session, query="original", limit=10)[1] == 1


def test_citation_context_changes_are_searchable() -> None:
    client, engine, _sessions = build_test_client()
    reference = register(client, engine, "context", "Original paper")
    assert (
        client.get("/references/page", params={"query": "contextual"}).json()[
            "total"
        ]
        == 0
    )
    result = client.post(
        f"/references/{reference['id']}/citation-contexts",
        json={
            "contexts": [{"context": "Contextual retrieval evidence"}],
        },
    )
    assert result.status_code == 200
    assert (
        client.get("/references/page", params={"query": "contextual"}).json()[
            "total"
        ]
        == 1
    )
