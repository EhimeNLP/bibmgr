from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pytest

from bibtex_reconstruction.clients.base import (
    APIClientError,
    BaseAPIClient,
)
from bibtex_reconstruction.clients.rate_limit import ProviderRateLimiter
from bibtex_reconstruction.config import settings
from bibtex_reconstruction.domain import (
    InputData,
    ReferenceData,
    VerifiedCitationInfo,
)


@dataclass
class FakeResponse:
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)


class DummyClient(BaseAPIClient):
    @property
    def api_name(self) -> str:
        return "Test API"

    @property
    def api_prefix(self) -> str:
        return "test_api"

    @property
    def base_url(self) -> str:
        return "https://api.crossref.org/works"

    def _execute_search(self, input_data):
        self._make_request(operation="metadata_search")
        return (
            VerifiedCitationInfo(
                title=input_data.parsed_data.title,
            ),
            None,
        )


class FinalCooldownClient(DummyClient):
    @property
    def api_prefix(self) -> str:
        return "final_cooldown_test_api"


def input_data() -> InputData:
    return InputData(
        parsed_data=ReferenceData(
            id="b0",
            title="Example",
            raw_text="Example",
        )
    )


def test_http_failure_logs_status_and_raises_safe_error(monkeypatch, caplog):
    client = DummyClient()
    monkeypatch.setattr(
        "bibtex_reconstruction.clients.base.requests.get",
        lambda *args, **kwargs: FakeResponse(status_code=403),
    )
    caplog.set_level(
        logging.WARNING,
        logger="bibtex_reconstruction.clients.base",
    )

    with pytest.raises(APIClientError) as raised:
        client.search(input_data())

    assert raised.value.status_code == 403
    assert raised.value.operation == "metadata_search"
    assert raised.value.safe_summary == (
        "error_type=HTTPError operation=metadata_search http_status=403"
    )
    assert "http_status=403" in caplog.text
    assert "operation=metadata_search" in caplog.text


def test_rate_limit_status_is_logged_and_retried(monkeypatch, caplog):
    client = DummyClient()
    responses = iter([
        FakeResponse(status_code=429, headers={"Retry-After": "0"}),
        FakeResponse(status_code=200),
    ])
    request_count = 0

    def fake_get(*args, **kwargs):
        nonlocal request_count
        request_count += 1
        return next(responses)

    monkeypatch.setattr(
        "bibtex_reconstruction.clients.base.requests.get",
        fake_get,
    )
    caplog.set_level(
        logging.WARNING,
        logger="bibtex_reconstruction.clients.base",
    )

    metadata, _ = client.search(input_data())

    assert metadata is not None
    assert request_count == 2
    assert "http_status=429" in caplog.text
    assert "retryable=True" in caplog.text


def test_final_rate_limit_response_delays_next_provider_request(monkeypatch):
    client = FinalCooldownClient()
    responses = iter(
        [
            FakeResponse(status_code=429, headers={"Retry-After": "0.02"}),
            FakeResponse(status_code=200),
        ]
    )
    monkeypatch.setattr(settings, "max_retries", 1)
    monkeypatch.setattr(
        "bibtex_reconstruction.clients.base.requests.get",
        lambda *args, **kwargs: next(responses),
    )

    with pytest.raises(APIClientError):
        client.search(input_data())
    started_at = time.monotonic()

    metadata, _ = client.search(input_data())

    assert metadata is not None
    assert time.monotonic() - started_at >= 0.015


def test_provider_rate_limiter_serializes_concurrent_calls():
    limiter = ProviderRateLimiter()
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def operation():
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.01)
        with state_lock:
            active -= 1

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(limiter.call, 0, operation)
            for _ in range(4)
        ]
        for future in futures:
            future.result()

    assert maximum_active == 1


def test_provider_rate_limiter_is_shared_by_provider_name():
    first = ProviderRateLimiter.for_provider("shared-test-provider")
    second = ProviderRateLimiter.for_provider("shared-test-provider")
    different = ProviderRateLimiter.for_provider("different-test-provider")

    assert first is second
    assert first is not different


def test_provider_cooldown_delays_all_following_requests():
    limiter = ProviderRateLimiter()
    limiter.call(
        0,
        lambda: "rate-limited",
        cooldown_after=lambda result: 0.02,
    )
    started_at = time.monotonic()

    limiter.call(0, lambda: None)

    assert time.monotonic() - started_at >= 0.015
