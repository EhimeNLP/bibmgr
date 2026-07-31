from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from bibmgr_backend.security import (
    BoundedTokenBucketStore,
    RateLimitPolicy,
    RequestProtection,
    RequestProtectionMiddleware,
    RequestRateLimitError,
)


class MonotonicClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_token_bucket_refills_and_returns_retry_after() -> None:
    clock = MonotonicClock()
    store = BoundedTokenBucketStore(max_keys=10, clock=clock)
    policy = RateLimitPolicy("test", requests_per_minute=60, burst=2)

    store.consume(policy, "client")
    store.consume(policy, "client")
    with pytest.raises(RequestRateLimitError) as captured:
        store.consume(policy, "client")
    assert captured.value.retry_after == 1

    clock.advance(1)
    store.consume(policy, "client")


def test_token_bucket_cardinality_is_bounded() -> None:
    store = BoundedTokenBucketStore(max_keys=3)
    policy = RateLimitPolicy("test", requests_per_minute=60, burst=1)

    for index in range(20):
        store.consume(policy, f"client-{index}")

    assert store.tracked_key_count == 3


@pytest.mark.parametrize(
    ("requests_per_minute", "burst"),
    [(0, 1), (1, 0)],
)
def test_rate_limit_policy_requires_positive_limits(
    requests_per_minute: int,
    burst: int,
) -> None:
    with pytest.raises(ValueError):
        RateLimitPolicy(
            "invalid",
            requests_per_minute=requests_per_minute,
            burst=burst,
        )


def test_authentication_start_has_a_stricter_per_client_policy() -> None:
    protection = RequestProtection(
        global_policy=RateLimitPolicy(
            "global", requests_per_minute=10_000, burst=100
        ),
        auth_start_policy=RateLimitPolicy(
            "auth-start", requests_per_minute=1, burst=1
        ),
    )

    protection.check_client(
        method="POST",
        path="/auth/email/start",
        client_ip="192.0.2.1",
    )
    with pytest.raises(RequestRateLimitError):
        protection.check_client(
            method="POST",
            path="/auth/email/start",
            client_ip="192.0.2.1",
        )

    protection.check_client(
        method="POST",
        path="/auth/email/start",
        client_ip="192.0.2.2",
    )


def test_authenticated_writes_use_an_additional_bucket() -> None:
    protection = RequestProtection(
        authenticated_policy=RateLimitPolicy(
            "authenticated", requests_per_minute=10_000, burst=100
        ),
        authenticated_write_policy=RateLimitPolicy(
            "write", requests_per_minute=1, burst=1
        ),
    )

    protection.check_authenticated_write("user-1")
    with pytest.raises(RequestRateLimitError):
        protection.check_authenticated_write("user-1")

    protection.check_authenticated_user("user-1")


def test_declared_oversized_body_is_rejected_before_route_parsing() -> None:
    application = FastAPI()
    protection = RequestProtection(max_request_body_bytes=8)
    application.add_middleware(
        RequestProtectionMiddleware,
        protection=protection,
    )

    @application.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    response = TestClient(application).post("/echo", content=b"123456789")

    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"]["code"] == "request_too_large"


def test_chunked_body_is_rejected_by_fastapi_integration() -> None:
    application = FastAPI()
    protection = RequestProtection(max_request_body_bytes=8)
    application.add_middleware(
        RequestProtectionMiddleware,
        protection=protection,
    )

    @application.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    response = TestClient(application).post(
        "/echo",
        content=(part for part in (b"12345", b"67890")),
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_streamed_oversized_body_is_rejected_without_content_length() -> None:
    response_messages: list[dict[str, Any]] = []
    request_messages = iter(
        [
            {
                "type": "http.request",
                "body": b"12345",
                "more_body": True,
            },
            {
                "type": "http.request",
                "body": b"67890",
                "more_body": False,
            },
        ]
    )

    async def receive() -> dict[str, Any]:
        return next(request_messages)

    async def send(message: dict[str, Any]) -> None:
        response_messages.append(message)

    async def consume_body(
        _scope: dict[str, Any],
        receive_message: Callable[[], Awaitable[dict[str, Any]]],
        send_message: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        more_body = True
        while more_body:
            message = await receive_message()
            more_body = bool(message.get("more_body"))
        await send_message(
            {"type": "http.response.start", "status": 204, "headers": []}
        )
        await send_message({"type": "http.response.body", "body": b""})

    middleware = RequestProtectionMiddleware(
        consume_body,
        protection=RequestProtection(max_request_body_bytes=8),
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/echo",
        "headers": [],
        "client": ("192.0.2.1", 12345),
    }

    asyncio.run(middleware(scope, receive, send))

    start = next(
        message
        for message in response_messages
        if message["type"] == "http.response.start"
    )
    assert start["status"] == 413


def test_rate_limited_response_has_retry_after() -> None:
    application = FastAPI()
    protection = RequestProtection(
        global_policy=RateLimitPolicy(
            "global", requests_per_minute=1, burst=1
        )
    )
    application.add_middleware(
        RequestProtectionMiddleware,
        protection=protection,
    )

    @application.get("/ok")
    def ok() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(application)
    assert client.get("/ok").status_code == 200
    limited = client.get("/ok")

    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1
    assert limited.json()["error"]["code"] == "rate_limited"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("BIBMGR_MAX_REQUEST_BODY_BYTES", "not-an-integer"),
        ("BIBMGR_RATE_LIMIT_GLOBAL_PER_MINUTE", "0"),
        ("BIBMGR_RATE_LIMIT_AUTH_START_BURST", "-1"),
        ("BIBMGR_RATE_LIMIT_AUTHENTICATED_WRITE_PER_MINUTE", "0"),
        ("BIBMGR_RATE_LIMIT_MAX_KEYS", "99"),
    ],
)
def test_invalid_request_protection_environment_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=name):
        RequestProtection.from_environment()
