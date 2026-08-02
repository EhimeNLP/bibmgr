from __future__ import annotations

from dataclasses import dataclass

import pytest

from bibtex_reconstruction.clients.base import APIClientError
from bibtex_reconstruction.clients.jstage import JStageClient
from bibtex_reconstruction.domain import InputData, ReferenceData


JSTAGE_ATOM = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/">
  <result><status>0</status><message/></result>
  <entry>
    <article_title>
      <en>Natural Language Processing</en>
      <ja>自然言語処理</ja>
    </article_title>
    <article_link>
      <en>https://example.test/en</en>
      <ja>https://example.test/ja</ja>
    </article_link>
    <author>
      <en><name>Koichi Hashida</name></en>
      <ja><name>橋田 浩一</name></ja>
    </author>
    <material_title>
      <en>The Journal of Tests</en>
      <ja>試験学会誌</ja>
    </material_title>
    <pubyear>2001</pubyear>
    <prism:doi>10.1541/example.121.195</prism:doi>
  </entry>
</feed>
""".encode()

JSTAGE_ERROR = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <result><status>ERR_001</status><message>ERR_001</message></result>
  <entry><title/></entry>
</feed>
"""


@dataclass
class FakeResponse:
    content: bytes


def input_data() -> InputData:
    return InputData(
        parsed_data=ReferenceData(
            id="ref-1",
            title="自然言語処理",
            raw_text="自然言語処理",
        )
    )


def test_jstage_parses_atom_and_prism_namespaces(monkeypatch):
    client = JStageClient()
    monkeypatch.setattr(
        client,
        "_make_request",
        lambda **kwargs: FakeResponse(JSTAGE_ATOM),
    )
    metadata, bibtex = client.search(input_data())

    assert metadata is not None
    assert metadata.title == "自然言語処理"
    assert metadata.authors == ["橋田 浩一"]
    assert metadata.venue == "試験学会誌"
    assert metadata.year == 2001
    assert metadata.doi == "10.1541/example.121.195"
    assert metadata.url == "https://example.test/ja"
    assert bibtex is None
    assert metadata.raw_payload


def test_jstage_rejects_service_error_with_empty_entry(monkeypatch):
    client = JStageClient()
    monkeypatch.setattr(
        client,
        "_make_request",
        lambda **kwargs: FakeResponse(JSTAGE_ERROR),
    )

    with pytest.raises(APIClientError) as raised:
        client.search(input_data())

    assert raised.value.safe_summary == (
        "error_type=ProviderResponseError operation=metadata_search"
    )


def test_jstage_rejects_malformed_xml(monkeypatch):
    client = JStageClient()
    monkeypatch.setattr(
        client,
        "_make_request",
        lambda **kwargs: FakeResponse(b"<feed><entry>"),
    )

    with pytest.raises(APIClientError) as raised:
        client.search(input_data())

    assert raised.value.safe_summary == (
        "error_type=XMLSyntaxError operation=search_pipeline"
    )
