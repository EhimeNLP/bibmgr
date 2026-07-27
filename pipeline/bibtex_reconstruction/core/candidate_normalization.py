"""Deterministic normalization before Rust registration validation."""

from __future__ import annotations

import bibtexparser
from bibtexparser.middlewares import MonthAbbreviationMiddleware


def normalize_candidate_source(source: str) -> str:
    """Normalize standard month names with bibtexparser when parsing succeeds."""

    try:
        library = bibtexparser.parse_string(
            source,
            append_middleware=[MonthAbbreviationMiddleware()],
        )
    except Exception:
        return source
    if len(library.entries) != 1 or library.failed_blocks:
        return source
    return bibtexparser.write_string(library).strip()
