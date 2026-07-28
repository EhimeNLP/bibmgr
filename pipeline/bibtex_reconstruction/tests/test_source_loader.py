import json

import pytest
from pydantic import ValidationError

from bibtex_reconstruction.application.source_loader import (
    load_metadata_document,
)


def metadata_payload() -> dict:
    return {
        "title": "Example source document",
        "authors": ["Source Author"],
        "year": "2025",
        "doi": None,
        "abstract": "Example abstract.",
        "reference_count": 2,
        "references": [
            {
                "id": "b0",
                "title": "First cited work",
                "authors": ["First Author"],
                "year": "2020",
                "doi": "10.1000/example",
                "venue": "Example Journal 1(2), 3-4",
                "raw_text": "First Author. First cited work. 2020.",
                "context": "Example citation context.",
            },
            {
                "id": "b1",
                "title": "Second cited work",
                "authors": ["Second Author"],
                "year": "2017a",
                "doi": None,
                "venue": None,
                "raw_text": "Second Author. Second cited work. 2017a.",
                "context": None,
            },
        ],
    }


def write_payload(tmp_path, payload: dict):
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    return input_path


def test_loader_accepts_metadata_extraction_document(tmp_path):
    document = load_metadata_document(
        write_payload(tmp_path, metadata_payload())
    )

    assert document.title == "Example source document"
    assert document.reference_count == 2
    assert len(document.references) == 2
    assert document.references[0].id == "b0"
    assert document.references[1].year == "2017a"
    assert document.references[1].comparison_year == 2017


def test_loader_rejects_reference_count_mismatch(tmp_path):
    payload = metadata_payload()
    payload["reference_count"] = 1

    with pytest.raises(ValidationError, match="reference_count"):
        load_metadata_document(write_payload(tmp_path, payload))


def test_loader_rejects_duplicate_reference_ids(tmp_path):
    payload = metadata_payload()
    payload["references"][1]["id"] = payload["references"][0]["id"]

    with pytest.raises(ValidationError, match="must be unique"):
        load_metadata_document(write_payload(tmp_path, payload))


def test_loader_rejects_unknown_transport_fields(tmp_path):
    payload = metadata_payload()
    payload["unexpected"] = "silently accepting this would hide schema drift"

    with pytest.raises(ValidationError, match="unexpected"):
        load_metadata_document(write_payload(tmp_path, payload))
