#!/usr/bin/env python3
"""Reject Markdown prose paragraphs split across physical lines."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(?:[^`]*)$")
HEADING_RE = re.compile(r"^ {0,3}#{1,6}(?:\s+|$)")
SETEXT_RE = re.compile(r"^ {0,3}(?:=+|-+)\s*$")
THEMATIC_RE = re.compile(r"^ {0,3}(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$")
LIST_RE = re.compile(r"^(?P<indent> {0,3})(?:[-+*]|\d+[.)])\s+(?P<body>.*)$")
LINK_DEFINITION_RE = re.compile(r"^ {0,3}\[[^]]+\]:\s*")
TABLE_DELIMITER_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
HTML_OPEN_RE = re.compile(r"^\s*<([A-Za-z][A-Za-z0-9-]*)(?:\s|>|/)")
IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "target",
}


def discover_markdown_files() -> list[Path]:
    """Return checked-in and unignored, untracked Markdown files."""
    try:
        completed = subprocess.run(
            [
                "git",
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                "*.md",
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return sorted(
            path
            for path in REPO_ROOT.rglob("*.md")
            if not any(part in IGNORED_DIRS for part in path.relative_to(REPO_ROOT).parts)
        )

    return sorted(
        path
        for raw_path in completed.stdout.splitlines()
        if raw_path and (path := REPO_ROOT / raw_path).is_file()
    )


def expand_paths(raw_paths: list[str]) -> list[Path]:
    if not raw_paths:
        return discover_markdown_files()

    paths: set[Path] = set()
    for raw_path in raw_paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = REPO_ROOT / path
        path = path.resolve()
        if path.is_dir():
            paths.update(
                candidate
                for candidate in path.rglob("*.md")
                if not any(part in IGNORED_DIRS for part in candidate.parts)
            )
        elif path.suffix.lower() == ".md" and path.is_file():
            paths.add(path)
        else:
            raise ValueError(f"not a Markdown file or directory: {raw_path}")
    return sorted(paths)


def table_line_indices(lines: list[str]) -> set[int]:
    table_lines: set[int] = set()
    for index, line in enumerate(lines):
        if not TABLE_DELIMITER_RE.match(line):
            continue
        table_lines.add(index)
        if index > 0 and "|" in lines[index - 1]:
            table_lines.add(index - 1)
        cursor = index + 1
        while cursor < len(lines) and lines[cursor].strip() and "|" in lines[cursor]:
            table_lines.add(cursor)
            cursor += 1
    return table_lines


def find_violations(path: Path) -> list[tuple[int, int, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    table_lines = table_line_indices(lines)
    violations: list[tuple[int, int, str]] = []
    paragraph_start: int | None = None
    fence_marker: str | None = None
    html_end: str | None = None
    in_frontmatter = bool(lines and lines[0].strip() == "---")

    for index, line in enumerate(lines):
        line_number = index + 1
        stripped = line.strip()

        if in_frontmatter:
            if index > 0 and stripped in {"---", "..."}:
                in_frontmatter = False
            continue

        if fence_marker is not None:
            closing_fence = rf"^ {{0,3}}{re.escape(fence_marker[0])}{{{len(fence_marker)},}}\s*$"
            if re.match(closing_fence, line):
                fence_marker = None
            continue

        fence_match = FENCE_RE.match(line)
        if fence_match:
            fence_marker = fence_match.group(1)
            paragraph_start = None
            continue

        if html_end is not None:
            if html_end in line.lower():
                html_end = None
            continue

        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                html_end = "-->"
            paragraph_start = None
            continue

        html_match = HTML_OPEN_RE.match(line)
        if html_match:
            tag = html_match.group(1).lower()
            if (
                f"</{tag}>" not in line.lower()
                and not stripped.endswith("/>")
                and tag not in {"br", "hr", "img", "input", "link", "meta"}
            ):
                html_end = f"</{tag}>"
            paragraph_start = None
            continue

        if not stripped:
            paragraph_start = None
            continue

        if index in table_lines:
            paragraph_start = None
            continue

        list_match = LIST_RE.match(line)
        if list_match:
            paragraph_start = line_number if list_match.group("body").strip() else None
            continue

        indented_code = line.startswith("    ") or line.startswith("\t")
        if indented_code and paragraph_start is None:
            continue

        if (
            HEADING_RE.match(line)
            or SETEXT_RE.match(line)
            or THEMATIC_RE.match(line)
            or LINK_DEFINITION_RE.match(line)
            or stripped.startswith(">")
            or stripped in {"$$", "\\[", "\\]"}
        ):
            paragraph_start = None
            continue

        if paragraph_start is not None:
            violations.append((line_number, paragraph_start, stripped))
        else:
            paragraph_start = line_number

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that each Markdown prose paragraph occupies one physical line."
    )
    parser.add_argument("paths", nargs="*", help="Markdown files or directories to check")
    args = parser.parse_args()

    try:
        paths = expand_paths(args.paths)
    except ValueError as error:
        parser.error(str(error))

    violation_count = 0
    for path in paths:
        for line_number, paragraph_start, text in find_violations(path):
            violation_count += 1
            try:
                display_path = path.relative_to(REPO_ROOT)
            except ValueError:
                display_path = path
            print(
                f"{display_path}:{line_number}: prose paragraph starting at line "
                f"{paragraph_start} spans multiple physical lines: {text}",
                file=sys.stderr,
            )

    if violation_count:
        print(
            f"found {violation_count} Markdown paragraph line violation(s)",
            file=sys.stderr,
        )
        return 1

    print(f"Markdown paragraph check passed ({len(paths)} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
