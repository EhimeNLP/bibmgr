"""Transport-level segmentation for damaged bibliography files."""

from __future__ import annotations

import re

from models import ReferenceData


_BLOCK_START = re.compile(
    r"(?im)^[ \t]*@(?P<kind>[a-z][a-z0-9_-]*)\s*[\{\(]"
)
_DIRECTIVE_TYPES = {"comment", "preamble", "string"}


def load_bibliography_fragments(source: str) -> list[ReferenceData]:
    """Split a source file without deciding whether any fragment is valid."""

    matches = list(_BLOCK_START.finditer(source))
    if not matches:
        chunks = [
            chunk.strip()
            for chunk in re.split(r"\n\s*\n+", source)
            if chunk.strip()
        ]
        return [
            ReferenceData(
                id=f"entry-{index:04d}",
                raw_text=chunk,
            )
            for index, chunk in enumerate(chunks, start=1)
        ]

    prefix = source[: matches[0].start()].strip()
    directives: list[str] = [prefix] if prefix else []
    entries: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        block = source[match.start() : end].strip()
        if match.group("kind").casefold() in _DIRECTIVE_TYPES:
            directives.append(block)
        else:
            entries.append(block)

    context = "\n\n".join(directives) or None
    return [
        ReferenceData(
            id=f"entry-{index:04d}",
            raw_text=entry,
            context=context,
        )
        for index, entry in enumerate(entries, start=1)
    ]
