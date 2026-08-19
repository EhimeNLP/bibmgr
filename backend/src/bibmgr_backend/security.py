"""Bounded request controls for resource-exhaustion resistance."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
import math
import os
from threading import Lock
import time

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


DEFAULT_MAX_REQUEST_BODY_BYTES = 1_048_576
DEFAULT_RATE_LIMIT_MAX_KEYS = 10_000


class RequestRateLimitError(RuntimeError):
    """A request exceeded one of the bounded token buckets."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many requests. Please retry later.")
        self.retry_after = max(1, retry_after)


class RequestBodyTooLargeError(RuntimeError):
    """A request body exceeded the configured byte limit."""


@dataclass(frozen=True)
class RateLimitPolicy:
    """A continuously refilled token-bucket policy."""

    name: str
    requests_per_minute: int
    burst: int

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name must not be empty")
        if self.requests_per_minute < 1:
            raise ValueError("requests_per_minute must be positive")
        if self.burst < 1:
            raise ValueError("burst must be positive")

    @property
    def tokens_per_second(self) -> float:
        return self.requests_per_minute / 60


@dataclass
class _TokenBucket:
    tokens: float
    updated_at: float


class BoundedTokenBucketStore:
    """Thread-safe LRU token buckets with a strict key-cardinality bound."""

    def __init__(
        self,
        *,
        max_keys: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_keys < 1:
            raise ValueError("max_keys must be positive")
        self.max_keys = max_keys
        self.clock = clock
        self._buckets: OrderedDict[tuple[str, str], _TokenBucket] = (
            OrderedDict()
        )
        self._lock = Lock()

    @property
    def tracked_key_count(self) -> int:
        with self._lock:
            return len(self._buckets)

    def consume(self, policy: RateLimitPolicy, identity: str) -> None:
        key = (policy.name, identity)
        now = self.clock()
        with self._lock:
            bucket = self._buckets.pop(key, None)
            if bucket is None:
                if len(self._buckets) >= self.max_keys:
                    self._buckets.popitem(last=False)
                bucket = _TokenBucket(
                    tokens=float(policy.burst),
                    updated_at=now,
                )
            else:
                elapsed = max(0.0, now - bucket.updated_at)
                bucket.tokens = min(
                    float(policy.burst),
                    bucket.tokens + elapsed * policy.tokens_per_second,
                )
                bucket.updated_at = now

            if bucket.tokens >= 1:
                bucket.tokens -= 1
                self._buckets[key] = bucket
                return

            self._buckets[key] = bucket
            retry_after = math.ceil(
                (1 - bucket.tokens) / policy.tokens_per_second
            )
        raise RequestRateLimitError(retry_after)


class RequestProtection:
    """Apply per-client and per-authenticated-user request policies."""

    def __init__(
        self,
        *,
        max_request_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES,
        global_policy: RateLimitPolicy | None = None,
        auth_start_policy: RateLimitPolicy | None = None,
        auth_verify_policy: RateLimitPolicy | None = None,
        auth_session_policy: RateLimitPolicy | None = None,
        authenticated_policy: RateLimitPolicy | None = None,
        authenticated_write_policy: RateLimitPolicy | None = None,
        max_keys: int = DEFAULT_RATE_LIMIT_MAX_KEYS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_request_body_bytes < 1:
            raise ValueError("max_request_body_bytes must be positive")
        self.max_request_body_bytes = max_request_body_bytes
        self.global_policy = global_policy or RateLimitPolicy(
            "client-global", requests_per_minute=600, burst=120
        )
        self.auth_start_policy = auth_start_policy or RateLimitPolicy(
            "auth-start", requests_per_minute=10, burst=20
        )
        self.auth_verify_policy = auth_verify_policy or RateLimitPolicy(
            "auth-verify", requests_per_minute=30, burst=30
        )
        self.auth_session_policy = auth_session_policy or RateLimitPolicy(
            "auth-session", requests_per_minute=180, burst=60
        )
        self.authenticated_policy = authenticated_policy or RateLimitPolicy(
            "authenticated-user", requests_per_minute=600, burst=120
        )
        self.authenticated_write_policy = (
            authenticated_write_policy
            or RateLimitPolicy(
                "authenticated-write",
                requests_per_minute=120,
                burst=30,
            )
        )
        self._store = BoundedTokenBucketStore(
            max_keys=max_keys,
            clock=clock,
        )

    @classmethod
    def from_environment(cls) -> RequestProtection:
        return cls(
            max_request_body_bytes=_bounded_environment_integer(
                "BIBMGR_MAX_REQUEST_BODY_BYTES",
                DEFAULT_MAX_REQUEST_BODY_BYTES,
                minimum=1_024,
                maximum=52_428_800,
            ),
            global_policy=_environment_policy(
                "client-global",
                "BIBMGR_RATE_LIMIT_GLOBAL",
                default_per_minute=600,
                default_burst=120,
            ),
            auth_start_policy=_environment_policy(
                "auth-start",
                "BIBMGR_RATE_LIMIT_AUTH_START",
                default_per_minute=10,
                default_burst=20,
            ),
            auth_verify_policy=_environment_policy(
                "auth-verify",
                "BIBMGR_RATE_LIMIT_AUTH_VERIFY",
                default_per_minute=30,
                default_burst=30,
            ),
            auth_session_policy=_environment_policy(
                "auth-session",
                "BIBMGR_RATE_LIMIT_AUTH_SESSION",
                default_per_minute=180,
                default_burst=60,
            ),
            authenticated_policy=_environment_policy(
                "authenticated-user",
                "BIBMGR_RATE_LIMIT_AUTHENTICATED",
                default_per_minute=600,
                default_burst=120,
            ),
            authenticated_write_policy=_environment_policy(
                "authenticated-write",
                "BIBMGR_RATE_LIMIT_AUTHENTICATED_WRITE",
                default_per_minute=120,
                default_burst=30,
            ),
            max_keys=_bounded_environment_integer(
                "BIBMGR_RATE_LIMIT_MAX_KEYS",
                DEFAULT_RATE_LIMIT_MAX_KEYS,
                minimum=100,
                maximum=1_000_000,
            ),
        )

    def check_client(self, *, method: str, path: str, client_ip: str) -> None:
        self._store.consume(self.global_policy, client_ip)
        route_policy = self._route_policy(method, path)
        if route_policy is not None:
            self._store.consume(route_policy, client_ip)

    def check_authenticated_user(self, user_id: str) -> None:
        self._store.consume(self.authenticated_policy, user_id)

    def check_authenticated_write(self, user_id: str) -> None:
        self._store.consume(self.authenticated_policy, user_id)
        self._store.consume(self.authenticated_write_policy, user_id)

    def _route_policy(
        self, method: str, path: str
    ) -> RateLimitPolicy | None:
        if method == "POST" and path == "/auth/email/start":
            return self.auth_start_policy
        if method == "POST" and path == "/auth/email/verify":
            return self.auth_verify_policy
        if method == "GET" and path == "/auth/session":
            return self.auth_session_policy
        return None


class RequestProtectionMiddleware:
    """Reject excessive traffic and oversized bodies before route parsing."""

    def __init__(self, app: ASGIApp, protection: RequestProtection) -> None:
        self.app = app
        self.protection = protection

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "")).upper()
        path = str(scope.get("path", ""))
        client = scope.get("client")
        client_ip = str(client[0]) if client else "unknown"
        try:
            self.protection.check_client(
                method=method,
                path=path,
                client_ip=client_ip,
            )
        except RequestRateLimitError as error:
            await _error_response(
                status_code=429,
                code="rate_limited",
                message=str(error),
                headers={"Retry-After": str(error.retry_after)},
            )(scope, receive, send)
            return

        content_length = _content_length(scope)
        if (
            content_length is not None
            and content_length > self.protection.max_request_body_bytes
        ):
            await _payload_too_large_response()(scope, receive, send)
            return

        received_bytes = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.protection.max_request_body_bytes:
                    raise RequestBodyTooLargeError
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLargeError:
            if response_started:
                raise
            await _payload_too_large_response()(scope, receive, send)


def _content_length(scope: Scope) -> int | None:
    values = [
        value
        for name, value in scope.get("headers", [])
        if name.lower() == b"content-length"
    ]
    if not values:
        return None
    try:
        lengths = {int(value) for value in values}
    except ValueError:
        return None
    if len(lengths) != 1:
        return None
    length = lengths.pop()
    return max(0, length)


def _payload_too_large_response() -> JSONResponse:
    return _error_response(
        status_code=413,
        code="request_too_large",
        message="The request body is too large.",
    )


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    response_headers = {"Cache-Control": "no-store", **(headers or {})}
    return JSONResponse(
        status_code=status_code,
        headers=response_headers,
        content={
            "schema_version": "1",
            "error": {
                "code": code,
                "message": message,
            },
        },
    )


def _environment_policy(
    name: str,
    prefix: str,
    *,
    default_per_minute: int,
    default_burst: int,
) -> RateLimitPolicy:
    return RateLimitPolicy(
        name=name,
        requests_per_minute=_bounded_environment_integer(
            f"{prefix}_PER_MINUTE",
            default_per_minute,
            minimum=1,
            maximum=1_000_000,
        ),
        burst=_bounded_environment_integer(
            f"{prefix}_BURST",
            default_burst,
            minimum=1,
            maximum=100_000,
        ),
    )


def _bounded_environment_integer(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    configured = os.environ.get(name)
    if configured is None:
        return default
    try:
        value = int(configured)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer.") from error
    if not minimum <= value <= maximum:
        raise RuntimeError(
            f"{name} must be between {minimum} and {maximum}."
        )
    return value
