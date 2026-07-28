from bibtex_reconstruction.parsing.bibtex import (
    fill_missing_bibtex_fields,
    inspect_bibtex,
)


def test_inspection_requires_core_identity_and_type_specific_venue():
    result = inspect_bibtex(
        "@inproceedings{key, title={}, author={Ada Example}}"
    )

    assert result.parsed is True
    assert result.complete is False
    assert result.missing_fields == ("title", "year", "booktitle")


def test_inspection_accepts_editor_as_bibliographic_responsibility():
    result = inspect_bibtex(
        """@inbook{key,
  title = {Collected Work},
  editor = {Ada Example},
  booktitle = {Test Collection},
  year = {2024}
}"""
    )

    assert result.complete is True


def test_fill_missing_fields_preserves_existing_values():
    enriched, filled = fill_missing_bibtex_fields(
        """@article{key,
  title = {Original Title},
  author = {Ada Example},
  journal = {Journal of Tests}
}""",
        [
            {
                "title": "Replacement Title",
                "year": "2024",
                "doi": "10.1000/example",
            }
        ],
    )

    assert filled == ["year", "doi"]
    assert "Original Title" in enriched
    assert "Replacement Title" not in enriched
    assert "year = {2024}" in enriched
    assert "doi = {10.1000/example}" in enriched
