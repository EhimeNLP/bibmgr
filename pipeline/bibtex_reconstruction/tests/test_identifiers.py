from core.identifiers import extract_dois, normalize_doi


def test_normalize_doi_accepts_url_and_removes_sentence_punctuation():
    assert (
        normalize_doi("https://doi.org/10.1000/Example.123.")
        == "10.1000/example.123"
    )


def test_extract_dois_deduplicates_values_in_input_order():
    assert extract_dois(
        "doi:10.1000/first",
        "See 10.2000/SECOND and https://doi.org/10.1000/first.",
    ) == ["10.1000/first", "10.2000/second"]


def test_normalize_doi_rejects_non_doi_text():
    assert normalize_doi("arXiv:1706.03762") is None
