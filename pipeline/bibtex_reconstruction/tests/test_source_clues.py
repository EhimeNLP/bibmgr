from core.source_clues import enrich_search_clues
from models import ReferenceData


def test_enrich_search_clues_uses_bibtexparser_and_name_parser():
    reference = ReferenceData(
        id="ref-1",
        raw_text="""@inproceedings{key,
  title = {{BERT}: Pre-training},
  author = {Doe, Jane and van Rossum, Guido},
  year = {2019},
  booktitle = {Proceedings of TestConf},
  doi = {10.1000/example}
}""",
    )

    clues = enrich_search_clues(reference)

    assert clues.title == "BERT: Pre-training"
    assert clues.authors == ["Doe, Jane", "van Rossum, Guido"]
    assert clues.year == "2019"
    assert clues.venue == "Proceedings of TestConf"
    assert clues.doi == "10.1000/example"
    assert reference.title is None


def test_enrich_search_clues_does_not_reject_unparseable_input():
    reference = ReferenceData(
        id="ref-1",
        raw_text="@article{broken",
    )

    clues = enrich_search_clues(reference)

    assert clues.id == "ref-1"
    assert clues.title is None
