"""Extract one BibTeX document from a Slack code block."""

from __future__ import annotations

import re


class InputError(ValueError):
    """Raised when a mention does not contain exactly one usable code block."""


CODE_BLOCK = re.compile(r"```([\s\S]*?)```")
SLACK_HTTP_LINK = re.compile(
    r"<(https?://[^\s>|]+)(?:\|[^>]*)?>",
    flags=re.IGNORECASE,
)


def extract_bibtex(text: str) -> str:
    matches = CODE_BLOCK.findall(text)
    if len(matches) != 1:
        raise InputError("exactly one code block is required")
    source = matches[0].strip("\r\n")
    lines = source.splitlines()
    if lines and lines[0].strip().lower() in {"bib", "bibtex"}:
        source = "\n".join(lines[1:]).strip("\r\n")
    source = _decode_slack_entities(source)
    if not source.strip():
        raise InputError("the code block is empty")
    return source


def _decode_slack_entities(value: str) -> str:
    decoded_links = SLACK_HTTP_LINK.sub(lambda match: match.group(1), value)
    return (
        decoded_links.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )
