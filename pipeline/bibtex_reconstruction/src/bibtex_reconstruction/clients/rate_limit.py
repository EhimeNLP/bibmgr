"""Thread-safe request pacing for one external API provider."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")


class ProviderRateLimiter:
    """Serialize provider requests and enforce a minimum start interval."""

    _registry_lock = threading.Lock()
    _registry: dict[str, ProviderRateLimiter] = {}

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_started_at: float | None = None
        self._blocked_until = 0.0

    @classmethod
    def for_provider(cls, provider: str) -> ProviderRateLimiter:
        """Return the process-wide limiter for one provider."""

        with cls._registry_lock:
            return cls._registry.setdefault(provider, cls())

    def call(
        self,
        minimum_interval: float,
        operation: Callable[[], T],
        *,
        cooldown_after: Callable[[T], float] | None = None,
        error_cooldown: float = 0,
    ) -> T:
        with self._lock:
            now = time.monotonic()
            earliest_start = self._blocked_until
            if self._last_started_at is not None:
                earliest_start = max(
                    earliest_start,
                    self._last_started_at + minimum_interval,
                )
            remaining = earliest_start - now
            if remaining > 0:
                time.sleep(remaining)
            self._last_started_at = time.monotonic()
            try:
                result = operation()
            except Exception:
                self._defer_unlocked(error_cooldown)
                raise
            if cooldown_after is not None:
                self._defer_unlocked(cooldown_after(result))
            return result

    def defer(self, seconds: float) -> None:
        """Apply a shared provider cooldown before any subsequent request."""

        with self._lock:
            self._defer_unlocked(seconds)

    def _defer_unlocked(self, seconds: float) -> None:
        self._blocked_until = max(
            self._blocked_until,
            time.monotonic() + max(seconds, 0.0),
        )
