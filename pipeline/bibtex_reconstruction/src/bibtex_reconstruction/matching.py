"""Metadata matching helpers that never mutate stored citation data."""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Sequence


def normalize_comparison_text(value: str) -> str:
    """Normalize a temporary comparison copy, not the persisted value."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    # BibTeX uses braces to preserve capitalization.  They are formatting,
    # not token boundaries (``{A}CL`` and ``ACL`` must compare identically).
    normalized = normalized.replace("{", "").replace("}", "")
    normalized = re.sub(r"\\[`'\"^~=.uvHckbdtr]\s*", "", normalized)
    normalized = re.sub(r"\\[a-zA-Z]+\s*", "", normalized)
    return " ".join(re.sub(r"[^\w]+", " ", normalized).split())


_comparison_text = normalize_comparison_text


def calculate_similarity(original_text: str, found_text: str) -> float:
    """Return normalized title similarity without changing either input."""

    if not original_text or not found_text:
        return 0.0
    original = _comparison_text(original_text)
    found = _comparison_text(found_text)
    if not original or not found:
        return 0.0
    return difflib.SequenceMatcher(None, original, found).ratio()


def calculate_author_similarity(
    original_authors: Sequence[str],
    found_authors: Sequence[str],
) -> float:
    """Compare author-name tokens while tolerating initials and ordering."""

    def tokens(authors: Sequence[str]) -> set[str]:
        return {
            token
            for author in authors
            for token in _comparison_text(author).split()
            if len(token) > 1
        }

    original = tokens(original_authors)
    found = tokens(found_authors)
    if not original or not found:
        return 0.0
    return len(original & found) / len(original | found)


def calculate_citation_similarity(
    original_title: str,
    found_title: str,
    *,
    original_authors: Sequence[str] = (),
    found_authors: Sequence[str] = (),
) -> float:
    """Combine normalized title and author evidence into one score."""

    title_score = calculate_similarity(original_title, found_title)
    if not title_score:
        return 0.0

    weighted_score = 0.70 * title_score
    total_weight = 0.70
    if original_authors and found_authors:
        weighted_score += 0.30 * calculate_author_similarity(
            original_authors,
            found_authors,
        )
        total_weight += 0.30
    return weighted_score / total_weight
