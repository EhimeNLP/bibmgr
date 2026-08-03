from bibtex_reconstruction.matching import (
    calculate_author_similarity,
    calculate_citation_similarity,
    calculate_similarity,
)


def test_title_comparison_normalizes_only_temporary_copies():
    original = (
        "EmoBank: Studying the Impact of Annotation Perspective and "
        "Representation Format"
    )
    provider = (
        "EmoBank: Studying the Impact of Annotation Perspective and\n"
        "    Representation Format"
    )

    assert calculate_similarity(original, provider) == 1.0
    assert "\n" not in original
    assert "\n" in provider


def test_bibtex_case_braces_do_not_change_title_identity():
    assert calculate_similarity(
        "GoodNewsEveryone: A Corpus",
        "{G}ood{N}ews{E}veryone: A Corpus",
    ) == 1.0


def test_author_comparison_normalizes_only_temporary_copies():
    original = ["Strapparava, Carlo", "Mihalcea, Rada"]
    provider = ["Carlo Strapparava", "Rada Mihalcea"]

    assert calculate_author_similarity(original, provider) == 1.0
    assert original == ["Strapparava, Carlo", "Mihalcea, Rada"]
    assert provider == ["Carlo Strapparava", "Rada Mihalcea"]


def test_exact_authors_and_year_support_a_shortened_provider_title():
    score = calculate_citation_similarity(
        "SemEval-2007 Task 14: Affective Text",
        "SemEval-2007 task 14",
        original_authors=["Carlo Strapparava", "Rada Mihalcea"],
        found_authors=["Carlo Strapparava", "Rada Mihalcea"],
    )

    assert score >= 0.80


def test_related_title_cannot_overcome_wrong_authors_and_year():
    score = calculate_citation_similarity(
        "An Analysis of Annotated Corpora for Emotion Classification in Text",
        "Review of Non-English Corpora Annotated for Emotion Classification in Text",
        original_authors=["Laura-Ana-Maria Bostan", "Roman Klinger"],
        found_authors=["Viktorija Leonova"],
    )

    assert score < 0.80
