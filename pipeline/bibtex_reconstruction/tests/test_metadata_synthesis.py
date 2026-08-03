from __future__ import annotations

import pytest

from bibtex_reconstruction.application.metadata_synthesis import (
    synthesize_metadata_bibtex,
)
from bibtex_reconstruction.domain import (
    CandidateResult,
    ReferenceData,
    VerifiedCitationInfo,
)
from bibtex_reconstruction.domain.enums import CandidateStatus


@pytest.mark.parametrize(
    ("publication_type", "entry_type", "venue", "publisher", "field"),
    [
        (
            "JournalArticle",
            "article",
            "Journal of Tests",
            None,
            "journal",
        ),
        (
            "Conference",
            "inproceedings",
            "Conference on Tests",
            None,
            "booktitle",
        ),
        ("Book", "book", None, "Test Press", "publisher"),
        (
            "BookSection",
            "incollection",
            "Handbook of Tests",
            "Test Press",
            "booktitle",
        ),
    ],
)
def test_supported_publication_types_generate_complete_entries(
    publication_type,
    entry_type,
    venue,
    publisher,
    field,
):
    reference = ReferenceData(
        id="ref-1",
        title="A Reliable Work",
        authors=["Ada Example"],
        year="2024",
        venue=venue,
        raw_text="Ada Example. A Reliable Work. 2024.",
    )
    candidate = CandidateResult(
        candidate_id="candidate",
        source_api="Metadata API",
        source_priority=10,
        status=CandidateStatus.MATCH,
        confidence_score=1.0,
        verified_info=VerifiedCitationInfo(
            title="A Reliable Work",
            authors=["Ada Example"],
            publication_types=[publication_type],
            year=2024,
            venue=venue,
            publisher=publisher,
        ),
    )

    result = synthesize_metadata_bibtex(reference, candidate)

    assert result is not None
    assert result.entry_type == entry_type
    assert result.bibtex.startswith(f"@{entry_type}{{")
    assert result.fields[field] == (publisher if field == "publisher" else venue)
