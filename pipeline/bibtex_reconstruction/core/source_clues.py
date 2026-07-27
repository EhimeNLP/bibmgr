"""Conservative search-clue extraction from a reference's raw BibTeX."""

from __future__ import annotations

import bibtexparser
from bibtexparser.middlewares import LatexDecodingMiddleware, SeparateCoAuthors

from core.identifiers import normalize_doi
from models import ReferenceData


def enrich_search_clues(reference: ReferenceData) -> ReferenceData:
    """Fill missing search fields using bibtexparser without gating the input."""

    if not reference.raw_text.strip():
        return reference.model_copy(deep=True)

    source = "\n\n".join(
        part
        for part in (reference.context, reference.raw_text)
        if part
    )
    try:
        library = bibtexparser.parse_string(
            source,
            append_middleware=[
                LatexDecodingMiddleware(),
                SeparateCoAuthors(),
            ],
        )
    except Exception:
        return reference.model_copy(deep=True)
    if not library.entries:
        return reference.model_copy(deep=True)

    entry = library.entries[0]

    def field_value(name: str) -> object | None:
        for key, field in entry.fields_dict.items():
            if key.casefold() != name.casefold():
                continue
            return field.value
        return None

    def string_field(name: str) -> str | None:
        value = field_value(name)
        return value.strip() if isinstance(value, str) and value.strip() else None

    authors = list(reference.authors)
    raw_authors = field_value("author")
    if not authors and isinstance(raw_authors, list):
        authors = [
            author.strip()
            for author in raw_authors
            if isinstance(author, str) and author.strip()
        ]

    return reference.model_copy(
        update={
            "title": reference.title or string_field("title"),
            "authors": authors,
            "year": reference.year or string_field("year"),
            "doi": reference.doi or normalize_doi(string_field("doi")),
            "venue": (
                reference.venue
                or string_field("journal")
                or string_field("booktitle")
            ),
        },
        deep=True,
    )
