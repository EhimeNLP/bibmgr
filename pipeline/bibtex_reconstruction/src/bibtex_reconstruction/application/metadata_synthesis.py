"""Deterministic BibTeX synthesis from one explicitly typed candidate."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..domain import (
    CandidateResult,
    FieldConflict,
    FieldProvenance,
    ReferenceData,
)
from ..matching import calculate_similarity, normalize_comparison_text
from ..parsing.bibtex import metadata_bibtex_fields, render_metadata_bibtex


_PUBLICATION_TYPE_TO_BIBTEX = {
    "article": "article",
    "book": "book",
    "bookchapter": "incollection",
    "booksection": "incollection",
    "conference": "inproceedings",
    "conferencepaper": "inproceedings",
    "incollection": "incollection",
    "inproceedings": "inproceedings",
    "journalarticle": "article",
    "monograph": "book",
    "proceedingsarticle": "inproceedings",
}

_VENUE_STOPWORDS = {"a", "an", "and", "for", "in", "of", "on", "the"}


@dataclass(frozen=True)
class SynthesizedCitation:
    bibtex: str
    entry_type: str
    fields: Mapping[str, str]
    provenance: Sequence[FieldProvenance]
    observed_conflicts: Sequence[FieldConflict]


def synthesize_metadata_bibtex(
    reference: ReferenceData,
    candidate: CandidateResult,
) -> SynthesizedCitation | None:
    """Build a complete entry without combining independent API candidates."""

    metadata = candidate.verified_info
    if metadata is None:
        return None
    entry_type = _entry_type(metadata.publication_types)
    if entry_type is None:
        return None
    if entry_type != "book" and not _venue_is_consistent(
        reference.venue, metadata.venue
    ):
        return None

    year = reference.comparison_year or metadata.year
    fields = metadata_bibtex_fields(
        entry_type=entry_type,
        title=metadata.title,
        authors=metadata.authors,
        year=year,
        venue=metadata.venue,
        publisher=metadata.publisher,
        volume=metadata.volume,
        number=metadata.number,
        pages=metadata.pages,
        doi=metadata.doi,
        url=metadata.url,
    )
    if not _fields_complete(entry_type, fields):
        return None

    bibtex = render_metadata_bibtex(
        entry_type=entry_type,
        citation_key=f"reconstructed-{candidate.candidate_id}",
        fields=fields,
    )
    conflicts: list[FieldConflict] = []
    if (
        reference.comparison_year
        and metadata.year
        and reference.comparison_year != metadata.year
    ):
        conflicts.append(
            FieldConflict(
                field="year",
                values={
                    "metadata_extraction": str(reference.comparison_year),
                    candidate.source_api: str(metadata.year),
                },
                reason=(
                    "the cited formal-version year was selected; the "
                    "provider year remains recorded as evidence"
                ),
            )
        )
    return SynthesizedCitation(
        bibtex=bibtex,
        entry_type=entry_type,
        fields=fields,
        provenance=_field_provenance(
            candidate,
            fields,
            entry_type=entry_type,
            year_from_input=reference.comparison_year is not None,
        ),
        observed_conflicts=conflicts,
    )


def _entry_type(publication_types: Sequence[str]) -> str | None:
    mapped = {
        mapped_type
        for publication_type in publication_types
        if (
            mapped_type := _PUBLICATION_TYPE_TO_BIBTEX.get(
                re.sub(r"[^a-z0-9]+", "", publication_type.casefold())
            )
        )
    }
    return next(iter(mapped)) if len(mapped) == 1 else None


def _fields_complete(entry_type: str, fields: Mapping[str, str]) -> bool:
    if not all(fields.get(name) for name in ("title", "author", "year")):
        return False
    required = {
        "article": ("journal",),
        "book": ("publisher",),
        "incollection": ("booktitle", "publisher"),
        "inproceedings": ("booktitle",),
    }.get(entry_type)
    return bool(required) and all(fields.get(name) for name in required)


def _field_provenance(
    candidate: CandidateResult,
    fields: Mapping[str, str],
    *,
    entry_type: str,
    year_from_input: bool,
) -> list[FieldProvenance]:
    attributes = {
        "author": "authors",
        "booktitle": "venue",
        "doi": "doi",
        "journal": "venue",
        "number": "number",
        "pages": "pages",
        "publisher": "publisher",
        "title": "title",
        "url": "url",
        "volume": "volume",
        "year": "year",
    }
    result = [
        FieldProvenance(
            field="entry_type",
            value=entry_type,
            source_api=candidate.source_api,
            source_attribute="publication_types",
            candidate_id=candidate.candidate_id,
        )
    ]
    for name, value in fields.items():
        from_input = name == "year" and year_from_input
        result.append(
            FieldProvenance(
                field=name,
                value=value,
                source_api=(
                    "metadata_extraction"
                    if from_input
                    else candidate.source_api
                ),
                source_attribute=(
                    "year" if from_input else attributes.get(name, name)
                ),
                candidate_id=None if from_input else candidate.candidate_id,
            )
        )
    return result


def _venue_is_consistent(
    original_venue: str | None,
    candidate_venue: str | None,
) -> bool:
    if not candidate_venue:
        return False
    if not original_venue:
        return True
    original = normalize_comparison_text(original_venue)
    candidate = normalize_comparison_text(candidate_venue)
    if not original or not candidate:
        return False
    if original in candidate or candidate in original:
        return True
    original_tokens = set(original.split())
    candidate_tokens = set(candidate.split())
    candidate_acronym = "".join(
        token[0]
        for token in candidate.split()
        if token not in _VENUE_STOPWORDS
    )
    original_acronym = "".join(
        token[0]
        for token in original.split()
        if token not in _VENUE_STOPWORDS
    )
    return (
        candidate_acronym in original_tokens
        or original_acronym in candidate_tokens
        or calculate_similarity(original, candidate) >= 0.50
    )
