from __future__ import annotations

import csv
import io
import json
import re
from typing import Any


def extract_essential_info(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = _repaired_metadata(payload)
    references = _expanded_references(payload.get("references") or [])
    repaired_references = [
        _repaired_reference(item, index)
        for index, item in enumerate(references)
        if isinstance(item, dict)
    ]
    return {
        "title": metadata.get("title"),
        "authors": metadata.get("authors") or [],
        "year": metadata.get("year"),
        "doi": metadata.get("doi"),
        "abstract": metadata.get("abstract"),
        "reference_count": len(references),
        "references": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "authors": item.get("authors") or [],
                "year": item.get("year"),
                "doi": item.get("doi"),
                "venue": item.get("venue"),
                "pages": item.get("pages"),
                "publication_info": item.get("publication_info"),
                "raw_text": item.get("raw_text"),
            }
            for item in repaired_references
        ],
    }


def _repaired_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(payload.get("metadata") or {})
    if not metadata and any(key in payload for key in ("title", "authors", "abstract", "year", "doi")):
        metadata = {
            "title": payload.get("title"),
            "authors": payload.get("authors") or [],
            "abstract": payload.get("abstract"),
            "year": payload.get("year"),
            "doi": payload.get("doi"),
        }
    raw = metadata.get("raw")
    if not isinstance(raw, dict):
        return metadata
    try:
        from .paddleocr_vl import parse_paddleocr_vl_payload

        parsed, _ = parse_paddleocr_vl_payload(raw)
    except Exception:
        return metadata
    if parsed.title and _metadata_title_needs_repair(metadata.get("title"), parsed.title):
        metadata["title"] = parsed.title
    if parsed.authors and not metadata.get("authors"):
        metadata["authors"] = parsed.authors
    if parsed.abstract and not metadata.get("abstract"):
        metadata["abstract"] = parsed.abstract
    return metadata


def _metadata_title_needs_repair(current: Any, candidate: str) -> bool:
    if not current:
        return True
    if not isinstance(current, str):
        return True
    if current == candidate:
        return False
    return len(current) > 80 or current.endswith("．") or current.endswith(".")


def _expanded_references(references: Any) -> list[dict[str, Any]]:
    if not isinstance(references, list):
        return []
    expanded: list[dict[str, Any]] = []
    for item in references:
        if not isinstance(item, dict):
            continue
        raw_text = item.get("raw_text")
        if isinstance(raw_text, str):
            try:
                from .heuristics import parse_reference_entry, split_reference_entries

                entries = split_reference_entries(raw_text)
                if len(entries) > 1:
                    for entry in entries:
                        parsed = parse_reference_entry(
                            entry,
                            index=len(expanded),
                            source=item.get("source") or "paddleocr-vl",
                            confidence=float(item.get("confidence", 0.45)),
                        )
                        expanded.append(parsed.to_dict())
                    continue
            except Exception:
                pass
        expanded.append(item)
    return expanded


def _repaired_reference(item: dict[str, Any], index: int) -> dict[str, Any]:
    repaired = dict(item)
    raw_text = item.get("raw_text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return repaired
    try:
        from .heuristics import parse_reference_entry

        parsed = parse_reference_entry(raw_text, index=index, source=item.get("source") or "paddleocr-vl", confidence=0.45)
    except Exception:
        return repaired

    current_authors = item.get("authors")
    if parsed.authors and (
        _reference_authors_need_repair(current_authors) or _has_more_reference_authors(parsed.authors, current_authors)
    ):
        repaired["authors"] = parsed.authors
    if parsed.title and not repaired.get("title"):
        repaired["title"] = parsed.title
    if parsed.venue and _reference_venue_needs_repair(repaired.get("venue"), parsed.venue, parsed.year):
        repaired["venue"] = parsed.venue
    if parsed.pages and not repaired.get("pages"):
        repaired["pages"] = parsed.pages
    if parsed.publication_info and _reference_publication_info_needs_repair(
        repaired.get("publication_info"), parsed.publication_info
    ):
        repaired["publication_info"] = parsed.publication_info
    if parsed.year and not repaired.get("year"):
        repaired["year"] = parsed.year
    if parsed.doi and not repaired.get("doi"):
        repaired["doi"] = parsed.doi
    return repaired


def _reference_authors_need_repair(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return True
    return any(_looks_like_non_author_reference_piece(item) for item in value)


def _has_more_reference_authors(parsed_authors: list[str], current: Any) -> bool:
    if not isinstance(current, list):
        return True
    return len(parsed_authors) > len(current)


def _reference_venue_needs_repair(current: Any, parsed_venue: str, parsed_year: str | None = None) -> bool:
    if not isinstance(current, str) or not current.strip():
        return True
    current_text = " ".join(current.split())
    parsed_text = " ".join(parsed_venue.split())
    if current_text == parsed_text:
        return False
    lowered_current = current_text.lower().rstrip(" ,.;:")
    if parsed_text.startswith(current_text) and len(parsed_text) > len(current_text) + 8:
        return True
    if lowered_current.endswith((" in", " of", " the", " proceedings")):
        return True
    if re.search(r"\b(?:pp?\.?|pages?)\s*\d", current_text, flags=re.IGNORECASE):
        return True
    if parsed_year and re.search(rf"(?:^|[,;\s]){re.escape(parsed_year)}[a-z]?\s*$", current_text):
        return True
    if current_text.startswith(parsed_text) and len(current_text) > len(parsed_text) + 8:
        return True
    return False


def _reference_publication_info_needs_repair(current: Any, parsed_publication_info: str) -> bool:
    if not isinstance(current, str) or not current.strip():
        return True
    current_text = " ".join(current.split())
    parsed_text = " ".join(parsed_publication_info.split())
    if current_text == parsed_text:
        return False
    return parsed_text.startswith(current_text) and len(parsed_text) > len(current_text) + 8


def _looks_like_non_author_reference_piece(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    lowered = value.lower()
    if any(marker in lowered for marker in ("proceedings", "conference", "workshop", "journal", "arxiv", "vol.", "no.", "pp.")):
        return True
    if any(marker in value for marker in ("大会", "学会", "フォーラム", "情報処理", "人工知能")):
        return True
    if "." in value and len(value) > 45:
        return True
    return False


def summarize_extraction(payload: dict[str, Any], fmt: str = "json") -> str:
    essential = extract_essential_info(payload)
    if fmt == "json":
        return json.dumps(essential, ensure_ascii=False, indent=2)
    if fmt == "markdown":
        return _to_markdown(essential)
    if fmt == "csv":
        return _to_csv(essential)
    if fmt == "text":
        return _to_text(essential)
    raise ValueError(f"Unsupported summary format: {fmt}")


def _to_text(essential: dict[str, Any]) -> str:
    authors = ", ".join(essential["authors"]) if essential["authors"] else "unknown authors"
    title = essential["title"] or "untitled"
    return f"{title} / {authors} / references: {essential['reference_count']}"


def _to_markdown(essential: dict[str, Any]) -> str:
    lines = [
        f"# {essential['title'] or 'Untitled Paper'}",
        "",
        f"- Authors: {', '.join(essential['authors']) if essential['authors'] else ''}",
        f"- Year: {essential['year'] or ''}",
        f"- DOI: {essential['doi'] or ''}",
        f"- References: {essential['reference_count']}",
        "",
        "## References",
    ]
    for index, reference in enumerate(essential["references"], start=1):
        label = reference["title"] or reference["raw_text"] or "Untitled reference"
        year = f" ({reference['year']})" if reference["year"] else ""
        doi = f" DOI: {reference['doi']}" if reference["doi"] else ""
        lines.append(f"{index}. {label}{year}{doi}")
    return "\n".join(lines)


def _to_csv(essential: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=["id", "title", "authors", "year", "doi", "venue", "pages", "publication_info", "raw_text"],
    )
    writer.writeheader()
    for reference in essential["references"]:
        writer.writerow(
            {
                **reference,
                "authors": "; ".join(reference["authors"]),
            }
        )
    return buffer.getvalue()
