from __future__ import annotations

from dataclasses import dataclass

from bibtex_reconstruction.clients.cinii import CiNiiClient
from bibtex_reconstruction.domain import InputData, ReferenceData


OLD_CRID = "https://cir.nii.ac.jp/crid/1572261549209025280"
FULL_CRID = "https://cir.nii.ac.jp/crid/1390290699812540032"


@dataclass
class FakeResponse:
    payload: dict | None = None
    text: str = ""

    def json(self):
        return self.payload


def test_multilingual_detail_selects_complete_b20_record(monkeypatch):
    search_payload = {
        "items": [
            {
                "@id": OLD_CRID,
                "title": "性格特性用語を用いた Big Five 尺度の標準化",
                "link": {"@id": OLD_CRID},
                "dc:creator": ["齊藤崇子"],
                "prism:publicationDate": "2001",
            },
            {
                "@id": FULL_CRID,
                "title": "性格特性用語を用いたBig Five尺度の標準化",
                "link": {"@id": FULL_CRID},
                "dc:creator": [
                    "齊藤 崇子",
                    "中村 知靖",
                    "遠藤 利彦",
                    "横山 まどか",
                ],
                "prism:publicationDate": "2001-03-31",
                "dc:identifier": [
                    {"@type": "cir:DOI", "@value": "10.15017/856"}
                ],
            },
        ]
    }
    old_detail = {
        "dc:title": [
            {
                "@language": "ja",
                "@value": "性格特性用語を用いた Big Five 尺度の標準化",
            }
        ],
        "creator": [
            {"foaf:name": [{"@language": "ja", "@value": "齊藤崇子"}]}
        ],
    }
    full_detail = {
        "dc:title": [
            {
                "@language": "en",
                "@value": (
                    "Standardization of Big Five scales using the "
                    "Adjective Cheek List"
                ),
            },
            {
                "@language": "ja",
                "@value": "性格特性用語を用いたBig Five尺度の標準化",
            },
        ],
        "creator": [
            {
                "foaf:name": [
                    {"@language": "en", "@value": "Saito Takako"},
                    {"@language": "ja", "@value": "齊藤 崇子"},
                ]
            },
            {
                "foaf:name": [
                    {"@language": "en", "@value": "Nakamura Tomoyasu"},
                    {"@language": "ja", "@value": "中村 知靖"},
                ]
            },
            {
                "foaf:name": [
                    {"@language": "en", "@value": "Endo Toshihiko"},
                    {"@language": "ja", "@value": "遠藤 利彦"},
                ]
            },
            {
                "foaf:name": [
                    {"@language": "en", "@value": "Yokoyama Madoka"},
                    {"@language": "ja", "@value": "横山 まどか"},
                ]
            },
        ],
        "productIdentifier": [
            {
                "identifier": {
                    "@type": "DOI",
                    "@value": "10.15017/856",
                }
            }
        ],
        "publication": {
            "prism:publicationName": [
                {"@language": "ja", "@value": "九州大学心理学研究"}
            ],
            "prism:publicationDate": "2001-03-31",
        },
    }
    official_bibtex = """@article{1390290699812540032,
author={齊藤, 崇子 and 中村, 知靖 and 遠藤, 利彦 and 横山, まどか},
title={性格特性用語を用いたBig Five尺度の標準化},
journal={九州大学心理学研究},
year={2001},
doi={10.15017/856}
}"""
    calls: list[tuple[str, dict | None]] = []

    def fake_request(*, url, params=None, **kwargs):
        calls.append((url, params))
        if url.endswith("/articles"):
            return FakeResponse(search_payload)
        if url == f"{OLD_CRID}.json":
            return FakeResponse(old_detail)
        if url == f"{FULL_CRID}.json":
            return FakeResponse(full_detail)
        if url == f"{FULL_CRID}.bib":
            return FakeResponse(text=official_bibtex)
        raise AssertionError(url)

    client = CiNiiClient()
    monkeypatch.setattr(client, "_make_request", fake_request)
    metadata, bibtex = client.search(
        InputData(
            parsed_data=ReferenceData(
                id="b20",
                title=(
                    "Standardization of Big Five Scales Using the "
                    "Adjective Check List"
                ),
                authors=[
                    "Takako Saito",
                    "Tomoyasu Nakamura",
                    "Toshihiko Endo",
                    "Madoka Yokoyama",
                ],
                year="2001",
                venue="Kyushu University Psychological Research",
                raw_text="Saito et al. 2001. Big Five.",
            )
        )
    )

    assert metadata is not None
    assert metadata.title == "性格特性用語を用いたBig Five尺度の標準化"
    assert (
        "Standardization of Big Five scales using the Adjective Cheek List"
        in metadata.alternative_titles
    )
    assert metadata.authors == [
        "Saito Takako",
        "Nakamura Tomoyasu",
        "Endo Toshihiko",
        "Yokoyama Madoka",
    ]
    assert metadata.doi == "10.15017/856"
    assert metadata.url == FULL_CRID
    assert bibtex == official_bibtex
    search_params = calls[0][1]
    assert search_params is not None
    assert "q" in search_params
    assert "title" not in search_params
    assert search_params["count"] == 10


def test_detail_requests_follow_similarity_score_not_provider_order(
    monkeypatch,
):
    urls = [f"https://cir.nii.ac.jp/crid/{index}" for index in range(4)]
    search_payload = {
        "items": [
            {
                "@id": url,
                "title": f"Candidate {index}",
                "link": {"@id": url},
                "dc:creator": ["Example Author"],
            }
            for index, url in enumerate(urls)
        ]
    }
    scores = {
        urls[0]: 0.10,
        urls[1]: 0.20,
        urls[2]: 0.70,
        urls[3]: 0.80,
    }
    calls: list[str] = []

    def fake_request(*, url, **kwargs):
        calls.append(url)
        if url.endswith("/articles"):
            return FakeResponse(search_payload)
        if url.endswith(".json"):
            return FakeResponse({})
        if url.endswith(".bib"):
            return None
        raise AssertionError(url)

    client = CiNiiClient()
    monkeypatch.setattr(client, "_make_request", fake_request)
    monkeypatch.setattr(
        client,
        "_score",
        lambda reference, metadata: scores[metadata.url],
    )
    monkeypatch.setattr(
        "bibtex_reconstruction.clients.cinii.settings.cinii_detail_candidate_count",
        2,
    )

    metadata, bibtex = client.search(
        InputData(
            parsed_data=ReferenceData(
                id="ref-1",
                title="Target title",
                authors=["Example Author"],
                raw_text="Example Author. Target title.",
            )
        )
    )

    assert metadata is not None
    assert metadata.url == urls[3]
    assert bibtex is None
    assert [url for url in calls if url.endswith(".json")] == [
        f"{urls[3]}.json",
        f"{urls[2]}.json",
    ]
