"""Identifier extraction and normalization for damaged bibliography sources."""

from __future__ import annotations

import re


_DOI_PATTERN = re.compile(
    r"(?i)\b10\.\d{4,9}/[-._;()/:a-z0-9]+",
)
_TRAILING_PUNCTUATION = ".,;:"


def normalize_doi(value: str | None) -> str | None:
    """Return the canonical bare DOI found in *value*, if any."""

    if not value:
        return None

    text = value.strip()
    text = re.sub(r"(?i)^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", text)
    match = _DOI_PATTERN.search(text)
    if not match:
        return None

    doi = match.group(0).rstrip(_TRAILING_PUNCTUATION)
    while doi.endswith((")", "]", "}")):
        opener = {")": "(", "]": "[", "}": "{"}[doi[-1]]
        if doi.count(opener) >= doi.count(doi[-1]):
            break
        doi = doi[:-1]
    return doi.lower()


def extract_dois(*values: str | None) -> list[str]:
    """Extract unique DOI identifiers while preserving their input order."""

    found: list[str] = []
    for value in values:
        if not value:
            continue
        for match in _DOI_PATTERN.finditer(value):
            doi = normalize_doi(match.group(0))
            if doi and doi not in found:
                found.append(doi)
    return found
