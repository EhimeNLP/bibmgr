"""Load and validate metadata_extraction JSON documents."""

from __future__ import annotations

import json
from pathlib import Path

from models import ReconstructionDocumentInput


def load_metadata_document(path: Path) -> ReconstructionDocumentInput:
    """Load the public reconstruction input contract from a UTF-8 JSON file."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return ReconstructionDocumentInput.model_validate(payload)
