from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .summary import summarize_extraction


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bibmgr-paper-parse",
        description="Extract essential metadata and references from paper_extractor JSON output.",
    )
    parser.add_argument("json_path", type=Path, help="Normalized paper_extractor JSON output.")
    parser.add_argument("--format", choices=["json", "markdown", "csv", "text"], default="json")
    parser.add_argument("-o", "--output", type=Path, help="Write parsed output to this path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.json_path.read_text(encoding="utf-8"))
        rendered = summarize_extraction(payload, fmt=args.format)
    except Exception as exc:
        parser.exit(2, f"error: {exc}\n")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + ("\n" if not rendered.endswith("\n") else ""), encoding="utf-8")
    else:
        sys.stdout.write(rendered + ("\n" if not rendered.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
