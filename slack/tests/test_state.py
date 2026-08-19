from __future__ import annotations

from bibmgr_slack.state import PendingStore


def test_pending_requests_are_user_bound_single_use_and_expire() -> None:
    now = [10.0]
    store = PendingStore(5, clock=lambda: now[0])
    request_id = store.create(
        user_id="U1", channel_id="C1", thread_ts="1.0", source="@misc{k,}"
    )

    assert store.consume(request_id, "U2")[0] == "wrong_user"
    assert store.consume(request_id, "U1")[0] == "ok"
    assert store.consume(request_id, "U1")[0] == "expired"

    expiring = store.create(
        user_id="U1", channel_id="C1", thread_ts="1.0", source="@misc{k,}"
    )
    now[0] = 16.0
    assert store.consume(expiring, "U1")[0] == "expired"


def test_event_ids_are_deduplicated_for_the_ttl() -> None:
    store = PendingStore(5, clock=lambda: 10.0)

    assert store.mark_event("Ev1")
    assert not store.mark_event("Ev1")
