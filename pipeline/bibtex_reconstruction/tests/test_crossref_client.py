from __future__ import annotations

from dataclasses import dataclass

from bibtex_reconstruction.clients.crossref import CrossrefClient
from bibtex_reconstruction.domain import InputData, ReferenceData


@dataclass
class FakeResponse:
    payload: dict

    def json(self):
        return self.payload


def test_preserves_structured_work_type_and_bibliographic_fields(monkeypatch):
    payload = {
        "message": {
            "items": [
                {
                    "DOI": "10.1000/example",
                    "type": "journal-article",
                    "title": ["A Reliable Paper"],
                    "author": [{"given": "Ada", "family": "Example"}],
                    "issued": {"date-parts": [[2024, 7, 2]]},
                    "container-title": ["Journal of Tests"],
                    "publisher": "Test Publisher",
                    "volume": "12",
                    "issue": "3",
                    "page": "10-20",
                    "URL": "https://doi.org/10.1000/example",
                }
            ]
        }
    }
    client = CrossrefClient()
    monkeypatch.setattr(
        client,
        "_make_request",
        lambda **kwargs: FakeResponse(payload),
    )

    metadata, bibtex = client.search(
        InputData(
            parsed_data=ReferenceData(
                id="ref-1",
                title="A Reliable Paper",
                raw_text="Ada Example. A Reliable Paper. 2024.",
            )
        )
    )

    assert metadata is not None
    assert metadata.publication_types == ["journal-article"]
    assert metadata.publication_date == "2024-7-2"
    assert metadata.publisher == "Test Publisher"
    assert metadata.volume == "12"
    assert metadata.number == "3"
    assert metadata.pages == "10-20"
    assert bibtex is None
