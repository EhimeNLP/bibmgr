from __future__ import annotations

import re
from collections.abc import Iterable

from .models import PaperMetadata, Reference

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}[a-z]?\b")
REFERENCE_HEADER_RE = re.compile(r"^\s*(references|bibliography|参考文献)\s*$", re.IGNORECASE)
SECTION_HEADER_RE = re.compile(r"^\s*(acknowledg(e)?ments?|appendix|supplementary|付録)\b", re.IGNORECASE)
NUMBERED_REFERENCE_RE = re.compile(r"^\s*(?:\[(?P<bracket>\d+)\]|(?P<plain>\d+)[.)])\s*(?P<body>.+)")


def normalize_space(text: str | None) -> str | None:
    if not text:
        return None
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized or None


def clean_doi(text: str | None) -> str | None:
    if not text:
        return None
    match = DOI_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,;)").lower()


def split_people(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"\s*(?:;|\band\b|, and)\s*", value)
    else:
        parts = list(value)
    people: list[str] = []
    for part in parts:
        name = normalize_space(str(part))
        if name and name not in people:
            people.append(name)
    return people


def guess_title_from_text(text: str) -> str | None:
    lines = [normalize_space(line) for line in text.splitlines()]
    header_lines: list[str | None] = []
    for line in lines[:40]:
        if line and line.lower().startswith(("abstract", "introduction", "keywords")):
            break
        if line and REFERENCE_HEADER_RE.match(line):
            break
        header_lines.append(line)
    candidates = [
        line
        for line in header_lines
        if line
        and 8 <= len(line) <= 220
        and not NUMBERED_REFERENCE_RE.match(line)
        and not REFERENCE_HEADER_RE.match(line)
        and not line.lower().startswith(("abstract", "keywords", "arxiv:"))
    ]
    if not candidates:
        return None
    return max(candidates[:8], key=len)


def extract_reference_block(text: str) -> str:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if REFERENCE_HEADER_RE.match(line):
            start = index + 1
    if start is None:
        return ""
    block_lines: list[str] = []
    for line in lines[start:]:
        if SECTION_HEADER_RE.match(line) and block_lines:
            break
        block_lines.append(line)
    return "\n".join(block_lines).strip()


def split_reference_entries(reference_block: str) -> list[str]:
    entries: list[str] = []
    current: list[str] = []
    for raw_line in reference_block.splitlines():
        line = normalize_space(raw_line)
        if not line:
            if current:
                entries.append(" ".join(current))
                current = []
            continue
        numbered = NUMBERED_REFERENCE_RE.match(line)
        if numbered and current:
            entries.append(" ".join(current))
            current = [numbered.group("body")]
            continue
        if numbered:
            current = [numbered.group("body")]
            continue
        if current:
            current.append(line)
        else:
            current = [line]
    if current:
        entries.append(" ".join(current))
    entries = [entry for entry in entries if len(entry) >= 12]
    if len(entries) == 1:
        unnumbered_entries = _split_unnumbered_reference_entries(entries[0])
        if len(unnumbered_entries) > 1:
            return unnumbered_entries
    return entries


def parse_reference_entry(raw_text: str, index: int, source: str, confidence: float) -> Reference:
    text = normalize_space(raw_text) or raw_text.strip()
    year_match = YEAR_RE.search(text)
    year = year_match.group(0) if year_match else None
    doi = clean_doi(text)
    title = _guess_reference_title(text, year_match.start() if year_match else None)
    authors = _guess_reference_authors(text, year_match.start() if year_match else None)
    venue = _guess_reference_venue(text, title)
    return Reference(
        id=f"b{index}",
        raw_text=text,
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        venue=venue,
        source=source,
        confidence=confidence,
    )


def extract_metadata_from_text(text: str, source: str = "paddleocr-vl") -> PaperMetadata:
    doi = clean_doi(text)
    title = guess_title_from_text(text)
    year_match = YEAR_RE.search(text[:4000])
    confidence = 0.35 if title else 0.15
    return PaperMetadata(
        title=title,
        year=year_match.group(0) if year_match else None,
        doi=doi,
        source=source,
        confidence=confidence,
    )


def extract_references_from_text(text: str, source: str = "paddleocr-vl") -> list[Reference]:
    block = extract_reference_block(text)
    if not block:
        return []
    entries = split_reference_entries(block)
    return [
        parse_reference_entry(entry, index=index, source=source, confidence=0.45)
        for index, entry in enumerate(entries)
    ]


def _guess_reference_title(text: str, year_start: int | None) -> str | None:
    quoted = re.search(r"[\"“](?P<title>[^\"”]{8,220})[\"”]", text)
    if quoted:
        return normalize_space(quoted.group("title"))
    _, title, _ = _split_reference_front_matter(text, year_start)
    if title:
        return title
    if year_start is None:
        return None
    after_year = text[_year_token_end(text, year_start) :]
    sentence_parts = [normalize_space(part) for part in re.split(r"\.\s+", after_year, maxsplit=3)]
    for part in sentence_parts:
        if part and 8 <= len(part) <= 220 and not DOI_RE.search(part):
            return part.rstrip(".")
    return None


def _split_unnumbered_reference_entries(text: str) -> list[str]:
    normalized = normalize_space(text)
    if not normalized:
        return []

    starts: list[int] = []
    candidate_positions = [0]
    candidate_positions.extend(
        match.end()
        for match in re.finditer(r"\.\s+", normalized)
        if not _ends_with_initial(normalized[: match.start() + 1])
    )
    for position in candidate_positions:
        candidate = normalized[position:]
        match = re.match(
            r"(?P<lead>[A-ZÀ-ÖØ-Þ][\s\S]{2,900}?\.\s+(?:19|20)\d{2}[a-z]?\.)",
            candidate,
        )
        if match and _looks_like_unnumbered_reference_start(match.group("lead")):
            starts.append(position)

    starts = sorted(dict.fromkeys(starts))
    if len(starts) <= 1:
        return [normalized]

    entries: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(normalized)
        entry = normalized[start:end].strip()
        if len(entry) >= 12:
            entries.append(entry)
    return entries or [normalized]


def _looks_like_unnumbered_reference_start(lead: str) -> bool:
    year_match = re.search(r"\.\s+(?:19|20)\d{2}[a-z]?\.$", lead)
    if not year_match:
        return False
    author_segment = lead[: year_match.start()].strip(" .,")
    lowered = author_segment.lower()
    if re.search(r"\b(?:in proceedings|proceedings|conference|workshop|journal|transactions|pages|vol|volume)\b", lowered):
        return False
    if ":" in author_segment or re.search(r"\d", author_segment):
        return False
    if _has_non_initial_period(author_segment):
        return False
    return bool(_split_reference_authors(author_segment))


def _ends_with_initial(text: str) -> bool:
    return bool(re.search(r"\b[A-Z]\.$", text.strip()))


def _has_non_initial_period(text: str) -> bool:
    for match in re.finditer(r"\.", text):
        if not _ends_with_initial(text[: match.start() + 1]):
            return True
    return False


def _guess_reference_authors(text: str, year_start: int | None) -> list[str]:
    author_segment, _, _ = _split_reference_front_matter(text, year_start)
    if not author_segment:
        return []
    return _split_reference_authors(author_segment)


def _year_token_end(text: str, year_start: int) -> int:
    match = re.match(r"(?:19|20)\d{2}[a-z]?", text[year_start:])
    if match:
        return year_start + len(match.group(0))
    return year_start + 4


def _guess_reference_venue(text: str, title: str | None) -> str | None:
    year_match = YEAR_RE.search(text)
    _, _, venue = _split_reference_front_matter(text, year_match.start() if year_match else None)
    if venue:
        return venue
    if title:
        marker = text.find(title)
        if marker >= 0:
            tail = text[marker + len(title) :]
            parts = [normalize_space(part) for part in tail.split(".")]
            for part in parts:
                if part and 4 <= len(part) <= 140 and not DOI_RE.search(part) and not _looks_like_year_tail(part):
                    return part
    return None


def _split_reference_front_matter(text: str, year_start: int | None) -> tuple[str | None, str | None, str | None]:
    """Split common academic references into author/title/venue prefixes.

    Most PaddleOCR-VL text for Japanese proceedings papers is shaped as
    "authors. title. venue, pages, year".  Splitting authors by every comma
    before the year pulls venue and page spans into the author list, so we
    first isolate the author sentence.
    """
    front = text[:year_start] if year_start is not None else text[:240]
    front = (normalize_space(front) or "").strip(" ,;")
    if not front:
        return None, None, None

    author_boundary = _find_sentence_boundary(front)
    if author_boundary is None:
        return front.strip(" .,"), None, None

    authors = front[:author_boundary].strip(" .,")
    rest = front[author_boundary + 1 :].strip(" .,")
    if not rest:
        return authors, None, None

    title_boundary = _find_sentence_boundary(rest)
    if title_boundary is None:
        arxiv_match = re.search(r"\barxiv\s*:\s*\d{4}\.\d+(?:v\d+)?", rest, flags=re.IGNORECASE)
        if arxiv_match:
            title = rest[: arxiv_match.start()].strip(" .,")
            venue = rest[arxiv_match.start() :].strip(" .,")
            return authors or None, title or None, venue or None
        return authors, rest.strip(" .,"), None

    title = rest[:title_boundary].strip(" .,")
    venue = rest[title_boundary + 1 :].strip(" .,")
    return authors or None, title or None, venue or None


def _find_sentence_boundary(text: str) -> int | None:
    for match in re.finditer(r"\.(?=\s|$)", text):
        index = match.start()
        prefix = text[: index + 1].strip()
        suffix = text[match.end() :].strip()
        token_match = re.search(r"([A-Za-z]+)\.$", prefix)
        token = token_match.group(1) if token_match else ""
        if token in {"Vol", "No", "pp", "Fig"}:
            continue
        if len(token) == 1 and token.isupper() and suffix:
            continue
        return index
    return None


def _split_reference_authors(author_segment: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", author_segment).strip(" .,")
    if not cleaned:
        return []
    if "et al" in cleaned.lower():
        cleaned = re.sub(r"\bet\s+al\.?", "et al.", cleaned, flags=re.IGNORECASE)
    if "," in cleaned:
        parts = [part.strip() for part in cleaned.split(",") if part.strip()]
    else:
        parts = split_people(cleaned)

    authors: list[str] = []
    for part in parts:
        name = re.sub(r"^(?:and|&)\s+", "", part.strip(), flags=re.IGNORECASE).strip(" .,")
        name = normalize_space(name)
        if name and name.lower() == "et al":
            name = "et al."
        if name and _looks_like_reference_author_name(name) and name not in authors:
            authors.append(name)
    return authors


def _looks_like_reference_author_name(name: str) -> bool:
    lowered = name.lower()
    if re.search(r"\b(?:proceedings|conference|workshop|journal|transactions|arxiv|vol|no|pp)\b", lowered):
        return False
    if re.search(r"\b\d+\s*[–-]\s*\d+\b", name):
        return False
    if any(marker in name for marker in ("大会", "学会", "フォーラム", "情報処理", "人工知能", "第 ")):
        return False
    if len(name) > 90:
        return False
    return True


def _looks_like_year_tail(text: str) -> bool:
    return bool(re.fullmatch(r"[,.\s]*(?:19|20)\d{2}[,.\s]*", text))
