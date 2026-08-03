from __future__ import annotations

from dataclasses import dataclass

from bibtex_reconstruction.clients.semantic_scholar import (
    SemanticScholarClient,
)
from bibtex_reconstruction.domain import InputData, ReferenceData


@dataclass
class FakeResponse:
    payload: dict

    def json(self):
        return self.payload


def test_retrieves_publication_type_and_provider_bibtex(monkeypatch):
    provider_bibtex = """@inproceedings{kingma2015adam,
  title={Adam: A Method for Stochastic Optimization},
  author={Diederik P. Kingma and Jimmy Ba},
  booktitle={International Conference on Learning Representations},
  year={2015}
}"""
    payload = {
        "data": [
            {
                "paperId": "adam",
                "title": "Adam: A Method for Stochastic Optimization",
                "authors": [
                    {"name": "Diederik P. Kingma"},
                    {"name": "Jimmy Ba"},
                ],
                "year": 2014,
                "venue": "International Conference on Learning Representations",
                "publicationTypes": ["Conference"],
                "publicationDate": "2014-12-22",
                "journal": {"pages": "1-15"},
                "externalIds": {"ArXiv": "1412.6980"},
                "url": "https://www.semanticscholar.org/paper/adam",
                "citationStyles": {"bibtex": provider_bibtex},
            }
        ]
    }
    client = SemanticScholarClient()
    request: dict[str, object] = {}

    def fake_request(**kwargs):
        request.update(kwargs)
        return FakeResponse(payload)

    monkeypatch.setattr(client, "_make_request", fake_request)
    metadata, bibtex = client.search(
        InputData(
            parsed_data=ReferenceData(
                id="b11",
                title="Adam: A Method for Stochastic Optimization",
                raw_text="Kingma and Ba. Adam. ICLR 2015.",
            )
        )
    )

    assert metadata is not None
    assert metadata.publication_types == ["Conference"]
    assert metadata.publication_date == "2014-12-22"
    assert metadata.pages == "1-15"
    assert bibtex == provider_bibtex
    assert "publicationTypes" in request["params"]["fields"]
    assert "citationStyles" in request["params"]["fields"]
    assert client.direct_bibtex_eligible is True
    assert client.authoritative_bibtex is False
