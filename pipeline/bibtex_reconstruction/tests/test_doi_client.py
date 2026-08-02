import pytest

from bibtex_reconstruction.clients.base import APIClientError
from bibtex_reconstruction.clients.doi import DoiContentNegotiationClient


class FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_fetch_bibtex_uses_content_negotiation():
    session = FakeSession(
        FakeResponse(200, "@article{key,\n  title = {Example}\n}\n")
    )

    result = DoiContentNegotiationClient(session=session).fetch_bibtex(
        "https://doi.org/10.1000/EXAMPLE"
    )

    assert result == "@article{key,\n  title = {Example}\n}"
    assert session.calls[0][0].endswith("/10.1000/example")
    assert (
        session.calls[0][1]["headers"]["Accept"]
        == "application/x-bibtex"
    )


def test_fetch_bibtex_treats_missing_metadata_as_no_candidate():
    session = FakeSession(FakeResponse(204))

    assert (
        DoiContentNegotiationClient(session=session).fetch_bibtex(
            "10.1000/missing"
        )
        is None
    )


def test_fetch_bibtex_reports_http_status_without_response_content():
    session = FakeSession(FakeResponse(503, "sensitive response body"))

    with pytest.raises(APIClientError) as raised:
        DoiContentNegotiationClient(session=session).fetch_bibtex(
            "10.1000/unavailable"
        )

    assert raised.value.safe_summary == (
        "error_type=HTTPError "
        "operation=doi_content_negotiation "
        "http_status=503"
    )
    assert "sensitive response body" not in str(raised.value)
