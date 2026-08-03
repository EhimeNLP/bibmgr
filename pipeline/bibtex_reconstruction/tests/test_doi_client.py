import socket

import pytest

from bibtex_reconstruction.clients.base import APIClientError
from bibtex_reconstruction.clients.doi import DoiContentNegotiationClient


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        text: str = "",
        *,
        url: str = "https://doi.org/10.1000/example",
        location: str | None = None,
        chunks: list[bytes] | None = None,
        content_length: int | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.url = url
        self.content = text.encode()
        self.chunks = chunks if chunks is not None else [self.content]
        self.iterated_chunks = 0
        self.closed = False
        self.headers = {}
        if location:
            self.headers["Location"] = location
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def iter_content(self, chunk_size):
        for chunk in self.chunks:
            self.iterated_chunks += 1
            yield chunk

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses: FakeResponse | list[FakeResponse]) -> None:
        if isinstance(responses, list):
            self.responses = iter(responses)
        else:
            self.responses = iter([responses])
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def public_resolver(host, port, **kwargs):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("93.184.216.34", port),
        )
    ]


def test_fetch_bibtex_uses_content_negotiation():
    session = FakeSession(
        FakeResponse(200, "@article{key,\n  title = {Example}\n}\n")
    )

    result = DoiContentNegotiationClient(
        session=session,
        resolver=public_resolver,
    ).fetch_bibtex("https://doi.org/10.1000/EXAMPLE")

    assert result == "@article{key,\n  title = {Example}\n}"
    assert session.calls[0][0].endswith("/10.1000/example")
    assert (
        session.calls[0][1]["headers"]["Accept"]
        == "application/x-bibtex"
    )


def test_fetch_bibtex_treats_missing_metadata_as_no_candidate():
    session = FakeSession(FakeResponse(204))

    assert (
        DoiContentNegotiationClient(
            session=session,
            resolver=public_resolver,
        ).fetch_bibtex("10.1000/missing")
        is None
    )


def test_fetch_bibtex_reports_http_status_without_response_content():
    session = FakeSession(FakeResponse(503, "sensitive response body"))

    with pytest.raises(APIClientError) as raised:
        DoiContentNegotiationClient(
            session=session,
            resolver=public_resolver,
        ).fetch_bibtex("10.1000/unavailable")

    assert raised.value.safe_summary == (
        "error_type=HTTPError "
        "operation=doi_content_negotiation "
        "http_status=503"
    )
    assert "sensitive response body" not in str(raised.value)


def test_fetch_bibtex_rejects_redirect_to_private_network():
    redirect = FakeResponse(
        302,
        location="http://127.0.0.1/private",
    )
    session = FakeSession(redirect)

    result = DoiContentNegotiationClient(
        session=session,
        resolver=public_resolver,
    ).fetch_bibtex("10.1000/example")

    assert result is None
    assert len(session.calls) == 1
    assert redirect.closed


def test_fetch_bibtex_rejects_dns_rebinding():
    redirect = FakeResponse(
        302,
        location="https://rebind.example/citation",
    )
    session = FakeSession(redirect)

    def resolver(host, port, **kwargs):
        address = (
            "127.0.0.1"
            if host == "rebind.example"
            else "93.184.216.34"
        )
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, port),
            )
        ]

    result = DoiContentNegotiationClient(
        session=session,
        resolver=resolver,
    ).fetch_bibtex("10.1000/example")

    assert result is None
    assert len(session.calls) == 1


def test_fetch_bibtex_stops_streaming_at_size_limit(monkeypatch):
    response = FakeResponse(
        200,
        chunks=[b"123456", b"789012", b"must-not-be-read"],
    )
    session = FakeSession(response)
    monkeypatch.setattr(
        "bibtex_reconstruction.clients.doi.settings.doi_max_bytes",
        10,
    )

    result = DoiContentNegotiationClient(
        session=session,
        resolver=public_resolver,
    ).fetch_bibtex("10.1000/example")

    assert result is None
    assert response.iterated_chunks == 2
    assert response.closed
    assert session.calls[0][1]["stream"] is True
