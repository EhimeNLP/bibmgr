#!/usr/bin/env python3
"""Validate the public JSON Schema and representative DTOs."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "bibmgr-v1.schema.json"
EXPORT_RESULT = {
    "schema_version": "1",
    "source": "@misc{example,}\n",
    "profile": "modern",
    "venue_name_style": "full",
    "record_count": 1,
    "warnings": [],
}
EXPORT_WORKFLOW_RESULT = {
    **EXPORT_RESULT,
    "input_applied_fix_ids": [],
    "output_applied_fix_ids": [],
    "input_diagnostics": [],
    "output_diagnostics": [],
}


def main() -> None:
    with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)

    if not isinstance(schema, dict):
        raise TypeError(f"{SCHEMA_PATH} must contain a JSON object")

    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(EXPORT_RESULT)
    validator.validate(EXPORT_WORKFLOW_RESULT)

    invalid_workflow_result = {
        **EXPORT_WORKFLOW_RESULT,
        "input_diagnostics": "not-an-array",
    }
    if validator.is_valid(invalid_workflow_result):
        raise ValueError(
            "The root schema accepted invalid workflow-specific fields."
        )

    print(f"JSON Schema and representative DTOs are valid: {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
