from __future__ import annotations

from dataclasses import dataclass

from bibtex_reconstruction.clients.acl_anthology import AclAnthologyClient
from bibtex_reconstruction.domain import InputData, ReferenceData


ANTHOLOGY = r"""
@inproceedings{unrelated,
  title = {A Different Corpus},
  author = {Other, Alice},
  booktitle = {Proceedings of Somewhere},
  year = {2020},
  url = {https://aclanthology.org/2020.test-1.1/}
}

@inproceedings{bostan-etal-2020-goodnewseveryone,
  title = {{G}ood{N}ews{E}veryone: A Corpus of News Headlines Annotated with Emotions, Semantic Roles, and Reader Perception},
  author = {Bostan, Laura Ana Maria and Kim, Evgeny and Klinger, Roman},
  booktitle = {Proceedings of the Twelfth Language Resources and Evaluation Conference},
  year = {2020},
  url = {https://aclanthology.org/2020.lrec-1.194/}
}
"""

OFFICIAL_BIBTEX = r"""@inproceedings{bostan-etal-2020-goodnewseveryone,
  title = {{G}ood{N}ews{E}veryone: A Corpus of News Headlines Annotated with Emotions, Semantic Roles, and Reader Perception},
  author = {Bostan, Laura Ana Maria and Kim, Evgeny and Klinger, Roman},
  booktitle = {Proceedings of the Twelfth Language Resources and Evaluation Conference},
  year = {2020},
  url = {https://aclanthology.org/2020.lrec-1.194/}
}
"""


@dataclass
class FakeResponse:
    text: str


def test_searches_cached_official_index_and_fetches_per_paper_bibtex(
    tmp_path,
    monkeypatch,
):
    cache = tmp_path / "anthology.bib"
    cache.write_text(ANTHOLOGY, encoding="utf-8")
    client = AclAnthologyClient(cache_path=cache)
    requested: list[str] = []

    def fake_request(*, url, **kwargs):
        requested.append(url)
        return FakeResponse(OFFICIAL_BIBTEX)

    monkeypatch.setattr(client, "_make_request", fake_request)
    metadata, bibtex = client.search(
        InputData(
            parsed_data=ReferenceData(
                id="b3",
                title=(
                    "GoodNewsEveryone: A Corpus of News Headlines Annotated "
                    "with Emotions, Semantic Roles, and Reader Perception"
                ),
                authors=[
                    "Laura-Ana-Maria Bostan",
                    "Evgeny Kim",
                    "Roman Klinger",
                ],
                year="2020",
                raw_text="GoodNewsEveryone. LREC 2020.",
            )
        )
    )

    assert metadata is not None
    assert metadata.url == "https://aclanthology.org/2020.lrec-1.194/"
    assert metadata.year == 2020
    assert metadata.publication_types == ["inproceedings"]
    assert metadata.authors == [
        "Bostan, Laura Ana Maria",
        "Kim, Evgeny",
        "Klinger, Roman",
    ]
    assert bibtex == OFFICIAL_BIBTEX
    assert requested == [
        "https://aclanthology.org/2020.lrec-1.194.bib"
    ]
