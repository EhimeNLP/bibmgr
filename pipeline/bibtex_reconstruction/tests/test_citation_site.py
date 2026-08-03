import socket

from bibtex_reconstruction.clients.citation_site import (
    OfficialCitationClient,
)


def public_resolver(host, port, **kwargs):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("93.184.216.34", port),
        ),
    ]


class FakeResponse:
    def __init__(
        self,
        *,
        text: str,
        url: str,
        status_code: int = 200,
        content_type: str = "text/html; charset=utf-8",
        location: str | None = None,
    ) -> None:
        self.text = text
        self.url = url
        self.status_code = status_code
        self.content = text.encode()
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(self.content)),
        }
        if location:
            self.headers["Location"] = location


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def test_discovers_generic_bibtex_download_link():
    landing = FakeResponse(
        text="""<html><head>
          <link rel="alternate" type="application/x-bibtex"
                href="/citation/paper.bib">
        </head></html>""",
        url="https://publisher.example/paper",
    )
    export = FakeResponse(
        text="@article{key, title={Official Export}}",
        url="https://publisher.example/citation/paper.bib",
        content_type="application/x-bibtex",
    )
    session = FakeSession([landing, export])

    result = OfficialCitationClient(
        session=session,
        resolver=public_resolver,
    ).fetch_bibtex(
        "10.1000/example"
    )

    assert result is not None
    assert result.bibtex == "@article{key, title={Official Export}}"
    assert result.source_url.endswith("/citation/paper.bib")
    assert session.calls[1][0] == (
        "https://publisher.example/citation/paper.bib"
    )


def test_discovers_visible_embedded_bibtex_without_second_request():
    landing = FakeResponse(
        text="""<html><body><pre>
          @inproceedings{key, title={Embedded Citation}}
        </pre></body></html>""",
        url="https://repository.example/item",
    )
    session = FakeSession([landing])

    result = OfficialCitationClient(
        session=session,
        resolver=public_resolver,
    ).fetch_bibtex(
        "10.1000/example"
    )

    assert result is not None
    assert result.bibtex.startswith("@inproceedings")
    assert len(session.calls) == 1


def test_ignores_unsafe_citation_link():
    landing = FakeResponse(
        text='<a href="http://127.0.0.1/private.bib">BibTeX</a>',
        url="https://publisher.example/paper",
    )
    session = FakeSession([landing])

    result = OfficialCitationClient(
        session=session,
        resolver=public_resolver,
    ).fetch_bibtex(
        "10.1000/example"
    )

    assert result is None
    assert len(session.calls) == 1


def test_does_not_follow_redirect_to_private_network():
    redirect = FakeResponse(
        text="",
        url="https://doi.org/10.1000/example",
        status_code=302,
        location="http://127.0.0.1/private",
    )
    session = FakeSession([redirect])

    result = OfficialCitationClient(
        session=session,
        resolver=public_resolver,
    ).fetch_bibtex(
        "10.1000/example"
    )

    assert result is None
    assert len(session.calls) == 1


def test_rejects_hostname_resolving_to_private_network():
    landing = FakeResponse(
        text='<a href="http://127.0.0.1.nip.io/private.bib">BibTeX</a>',
        url="https://publisher.example/paper",
    )
    session = FakeSession([landing])

    def resolver(host, port, **kwargs):
        address = (
            "127.0.0.1"
            if host == "127.0.0.1.nip.io"
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

    result = OfficialCitationClient(
        session=session,
        resolver=resolver,
    ).fetch_bibtex("10.1000/example")

    assert result is None
    assert len(session.calls) == 1


def test_rejects_hostname_when_any_dns_record_is_not_public():
    redirect = FakeResponse(
        text="",
        url="https://doi.org/10.1000/example",
        status_code=302,
        location="https://mixed.example/private",
    )
    session = FakeSession([redirect])

    def resolver(host, port, **kwargs):
        addresses = (
            ["93.184.216.34", "::1"]
            if host == "mixed.example"
            else ["93.184.216.34"]
        )
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, port),
            )
            for address in addresses
        ]

    result = OfficialCitationClient(
        session=session,
        resolver=resolver,
    ).fetch_bibtex("10.1000/example")

    assert result is None
    assert len(session.calls) == 1


def test_revalidates_citation_hostname_before_request():
    landing = FakeResponse(
        text='<a href="https://rebind.example/paper.bib">BibTeX</a>',
        url="https://publisher.example/paper",
    )
    session = FakeSession([landing])
    rebind_lookups = 0

    def resolver(host, port, **kwargs):
        nonlocal rebind_lookups
        address = "93.184.216.34"
        if host == "rebind.example":
            rebind_lookups += 1
            if rebind_lookups > 1:
                address = "127.0.0.1"
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, port),
            )
        ]

    result = OfficialCitationClient(
        session=session,
        resolver=resolver,
    ).fetch_bibtex("10.1000/example")

    assert result is None
    assert rebind_lookups == 2
    assert len(session.calls) == 1


def test_default_transport_pins_the_validated_address(monkeypatch):
    client = OfficialCitationClient(resolver=public_resolver)
    requested: list[tuple[str, str]] = []

    def fake_pinned_get(url, *, address, headers):
        requested.append((url, address))
        return FakeResponse(
            text="@article{key, title={Pinned Citation}}",
            url=url,
            content_type="application/x-bibtex",
        )

    monkeypatch.setattr(client, "_pinned_get", fake_pinned_get)

    result = client.fetch_bibtex("10.1000/example")

    assert result is not None
    assert requested == [
        ("https://doi.org/10.1000/example", "93.184.216.34")
    ]
