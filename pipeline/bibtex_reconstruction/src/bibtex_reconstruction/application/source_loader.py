"""Load and validate metadata_extraction JSON documents."""

from __future__ import annotations

import json
from pathlib import Path

from ..domain import ReconstructionDocumentInput, ReferenceData


_DOCUMENT_METADATA_FIELDS = ("title", "authors", "year", "doi", "abstract")


def _normalize_extraction_result(payload: object) -> object:
    """Convert ``ExtractionResult.to_dict()`` into the reconstruction contract."""

    if not isinstance(payload, dict) or "metadata" not in payload:
        return payload
    metadata = payload.get("metadata")
    references = payload.get("references")
    if not isinstance(metadata, dict) or not isinstance(references, list):
        return payload

    normalized_references: list[object] = []
    for reference in references:
        if not isinstance(reference, dict):
            normalized_references.append(reference)
            continue
        normalized_references.append(
            {
                name: reference[name]
                for name in ReferenceData.model_fields
                if name in reference
            }
        )
    return {
        **{
            name: metadata[name]
            for name in _DOCUMENT_METADATA_FIELDS
            if name in metadata
        },
        "reference_count": len(references),
        "references": normalized_references,
    }


def load_metadata_document(path: Path) -> ReconstructionDocumentInput:
    """Load the public reconstruction input contract from a UTF-8 JSON file."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    normalized = _normalize_extraction_result(payload)
    return ReconstructionDocumentInput.model_validate(normalized)
