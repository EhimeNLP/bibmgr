"""Short-lived in-memory state for profile selections."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
from threading import Lock
import time
from typing import Callable


@dataclass(frozen=True)
class PendingExport:
    user_id: str
    channel_id: str
    thread_ts: str | None
    source: str
    expires_at: float


class PendingStore:
    def __init__(
        self,
        ttl_seconds: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._values: dict[str, PendingExport] = {}
        self._seen_events: dict[str, float] = {}
        self._lock = Lock()

    def mark_event(self, event_id: str) -> bool:
        now = self._clock()
        with self._lock:
            self._purge(now)
            if event_id in self._seen_events:
                return False
            self._seen_events[event_id] = now + self._ttl_seconds
            return True

    def create(
        self, *, user_id: str, channel_id: str, thread_ts: str | None, source: str
    ) -> str:
        now = self._clock()
        request_id = secrets.token_urlsafe(16)
        with self._lock:
            self._purge(now)
            self._values[request_id] = PendingExport(
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                source=source,
                expires_at=now + self._ttl_seconds,
            )
        return request_id

    def consume(self, request_id: str, user_id: str) -> tuple[str, PendingExport | None]:
        now = self._clock()
        with self._lock:
            self._purge(now)
            value = self._values.get(request_id)
            if value is None:
                return "expired", None
            if value.user_id != user_id:
                return "wrong_user", None
            return "ok", self._values.pop(request_id)

    def _purge(self, now: float) -> None:
        self._values = {
            key: value
            for key, value in self._values.items()
            if value.expires_at > now
        }
        self._seen_events = {
            key: expires_at
            for key, expires_at in self._seen_events.items()
            if expires_at > now
        }
