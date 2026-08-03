from __future__ import annotations

from dataclasses import dataclass

from bibtex_reconstruction.clients.arxiv import ArxivClient
from bibtex_reconstruction.domain import InputData, ReferenceData


ARXIV_ATOM = b"""\
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <published>2017-06-12T17:57:34Z</published>
    <title>Attention Is All You Need</title>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <arxiv:primary_category term="cs.CL"/>
  </entry>
</feed>
"""

ARXIV_ATOM_WITH_DOI = ARXIV_ATOM.replace(
    b"    <arxiv:primary_category term=\"cs.CL\"/>",
    b"""\
    <arxiv:primary_category term="cs.CL"/>
    <arxiv:doi>10.5555/example</arxiv:doi>""",
)

OFFICIAL_BIBTEX = """\
@misc{vaswani2023attentionneed,
  title={Attention Is All You Need},
  author={Ashish Vaswani and Noam Shazeer},
  year={2023},
  eprint={1706.03762},
  archivePrefix={arXiv},
  primaryClass={cs.CL},
  url={https://arxiv.org/abs/1706.03762},
}"""


@dataclass
class FakeResponse:
    content: bytes = b""
    text: str = ""
    status_code: int = 200


def input_data() -> InputData:
    return InputData(
        parsed_data=ReferenceData(
            id="ref-1",
            title="Attention Is All You Need",
            raw_text="Attention Is All You Need",
        )
    )


def test_arxiv_uses_official_bibtex_export_and_strips_version(monkeypatch):
    client = ArxivClient()
    requested_urls: list[str | None] = []

    def fake_request(url=None, **kwargs):
        requested_urls.append(url)
        if url is None:
            return FakeResponse(content=ARXIV_ATOM)
        return FakeResponse(text=OFFICIAL_BIBTEX)

    monkeypatch.setattr(client, "_make_request", fake_request)

    metadata, bibtex = client.search(input_data())

    assert metadata is not None
    assert metadata.url == "http://arxiv.org/abs/1706.03762v7"
    assert bibtex == OFFICIAL_BIBTEX
    assert requested_urls == [None, "https://arxiv.org/bibtex/1706.03762"]


def test_explicit_arxiv_id_uses_official_bibtex_without_atom_search(
    monkeypatch,
):
    client = ArxivClient()
    requested_urls: list[str | None] = []

    def fake_request(url=None, **kwargs):
        requested_urls.append(url)
        return FakeResponse(text=OFFICIAL_BIBTEX)

    monkeypatch.setattr(client, "_make_request", fake_request)
    metadata, bibtex = client.search(
        InputData(
            parsed_data=ReferenceData(
                id="ref-1",
                title="arXiv:1706.03762 Attention Is All You Need",
                authors=["Ashish Vaswani", "Noam Shazeer"],
                raw_text="arXiv:1706.03762",
            )
        )
    )

    assert metadata is not None
    assert metadata.title == "Attention Is All You Need"
    assert metadata.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert metadata.year == 2023
    assert metadata.url == "https://arxiv.org/abs/1706.03762"
    assert bibtex == OFFICIAL_BIBTEX
    assert requested_urls == ["https://arxiv.org/bibtex/1706.03762"]


def test_arxiv_official_entry_exports_to_misc_howpublished(monkeypatch):
    import bibmgr_native

    client = ArxivClient()

    def fake_request(url=None, **kwargs):
        if url is None:
            return FakeResponse(content=ARXIV_ATOM)
        return FakeResponse(text=OFFICIAL_BIBTEX)

    monkeypatch.setattr(client, "_make_request", fake_request)
    _, bibtex = client.search(input_data())

    exported = bibmgr_native.export(
        bibtex,
        profile="classical-bst",
    ).source

    assert exported.startswith("@misc{")
    assert "howpublished = {arXiv:1706.03762}" in exported
    assert "eprint =" not in exported
    assert "archiveprefix =" not in exported.casefold()


def test_arxiv_does_not_generate_bibtex_when_official_export_fails(monkeypatch):
    client = ArxivClient()

    def fake_request(url=None, **kwargs):
        if url is None:
            return FakeResponse(content=ARXIV_ATOM)
        return None

    monkeypatch.setattr(client, "_make_request", fake_request)

    metadata, bibtex = client.search(input_data())

    assert metadata is not None
    assert bibtex is None


def test_arxiv_published_work_exposes_doi_without_fetching_other_sources(
    monkeypatch,
):
    client = ArxivClient()

    def fail_official_fetch(arxiv_id):
        raise AssertionError(
            "arXiv export must not replace a published citation"
        )

    monkeypatch.setattr(
        client,
        "_make_request",
        lambda **kwargs: FakeResponse(content=ARXIV_ATOM_WITH_DOI),
    )
    monkeypatch.setattr(
        client,
        "_fetch_official_bibtex",
        fail_official_fetch,
    )
    metadata, bibtex = client.search(input_data())

    assert metadata is not None
    assert metadata.doi == "10.5555/example"
    assert bibtex is None
