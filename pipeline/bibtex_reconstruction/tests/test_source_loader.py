import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from services.source_loader import load_metadata_document


FIXTURE = Path(__file__).with_name("test_input.json")


def test_loader_accepts_metadata_extraction_document():
    document = load_metadata_document(FIXTURE)

    assert document.title.startswith("WRIME:")
    assert document.reference_count == 28
    assert len(document.references) == 28
    assert document.references[0].id == "b0"
    assert document.references[13].year == "2017a"
    assert document.references[13].comparison_year == 2017


def test_loader_rejects_reference_count_mismatch(tmp_path):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["reference_count"] = 27
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="reference_count"):
        load_metadata_document(input_path)


def test_loader_rejects_duplicate_reference_ids(tmp_path):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["references"][1]["id"] = payload["references"][0]["id"]
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="must be unique"):
        load_metadata_document(input_path)


def test_loader_rejects_unknown_transport_fields(tmp_path):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["unexpected"] = "silently accepting this would hide schema drift"
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="unexpected"):
        load_metadata_document(input_path)
