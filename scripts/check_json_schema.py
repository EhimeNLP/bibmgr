#!/usr/bin/env python3
"""Validate that the public JSON Schema is well-formed JSON."""

from __future__ import annotations

import json
from pathlib import Path


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "bibmgr-v1.schema.json"


def main() -> None:
    with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)

    if not isinstance(schema, dict):
        raise TypeError(f"{SCHEMA_PATH} must contain a JSON object")

    print(f"JSON Schema is valid JSON: {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
