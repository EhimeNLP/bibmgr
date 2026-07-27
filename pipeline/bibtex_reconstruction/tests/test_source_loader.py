from services.source_loader import load_bibliography_fragments


def test_loader_splits_damaged_entries_at_next_block():
    source = """@article{first,
  title = {Missing closing brace}

@misc{second,
  title = {Second}
}
"""

    references = load_bibliography_fragments(source)

    assert [reference.id for reference in references] == [
        "entry-0001",
        "entry-0002",
    ]
    assert references[0].raw_text.startswith("@article{first")
    assert references[1].raw_text.startswith("@misc{second")


def test_loader_preserves_string_directives_as_context():
    source = """@string{venue = "Journal of Tests"}

@article{first,
  journal = venue
}
"""

    references = load_bibliography_fragments(source)

    assert len(references) == 1
    assert references[0].context.startswith("@string")
    assert "@string" not in references[0].raw_text


def test_loader_accepts_plain_reference_paragraphs():
    references = load_bibliography_fragments(
        "First author. First title.\n\nSecond author. Second title."
    )

    assert len(references) == 2
    assert references[1].raw_text == "Second author. Second title."
