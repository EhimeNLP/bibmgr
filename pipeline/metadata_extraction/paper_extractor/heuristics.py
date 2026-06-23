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
    year_match = _select_reference_year_match(text)
    year = year_match.group(0) if year_match else None
    doi = clean_doi(text)
    title = _guess_reference_title(text, year_match.start() if year_match else None)
    authors = _guess_reference_authors(text, year_match.start() if year_match else None)
    publication_info = _guess_reference_publication_info(text, title, year_match)
    venue = _guess_reference_venue(text, title, publication_info, year)
    pages = _guess_reference_pages(publication_info or text)
    return Reference(
        id=f"b{index}",
        raw_text=text,
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        venue=venue,
        pages=pages,
        publication_info=publication_info,
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


def _guess_reference_publication_info(
    text: str,
    title: str | None,
    year_match: re.Match[str] | None,
) -> str | None:
    """Return the citation tail after the title.

    This field intentionally preserves page ranges and a trailing publication
    year, e.g. ``In Proceedings ..., pp. 17337–17342, 2024``.  It is useful
    when callers want a near-source citation fragment, while ``venue`` remains
    a normalized publication venue name.
    """
    _, _, venue_tail = _split_reference_front_matter(text, year_match.start() if year_match else None)
    if venue_tail:
        return _include_trailing_publication_year(text, venue_tail, year_match)
    if not title:
        return None
    marker = text.find(title)
    if marker < 0:
        return None
    tail = text[marker + len(title) :]
    parts = [normalize_space(part) for part in tail.split(".")]
    for part in parts:
        if part and 4 <= len(part) <= 220 and not DOI_RE.search(part) and not _looks_like_year_tail(part):
            return part
    return None


def _guess_reference_venue(
    text: str,
    title: str | None,
    publication_info: str | None = None,
    year: str | None = None,
) -> str | None:
    if publication_info:
        return _normalize_reference_venue(publication_info, year)
    year_match = _select_reference_year_match(text)
    publication_info = _guess_reference_publication_info(text, title, year_match)
    if publication_info:
        return _normalize_reference_venue(publication_info, year_match.group(0) if year_match else year)
    return None


def _guess_reference_pages(publication_info: str | None) -> str | None:
    if not publication_info:
        return None
    text = normalize_space(publication_info) or publication_info
    match = re.search(
        r"\b(?:pp?\.?|pages?)\s*(?P<pages>[A-Za-z]?\d+\s*[–-]\s*[A-Za-z]?\d+|[A-Za-z]?\d+)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return normalize_space(match.group("pages"))
    # Journal-style references often encode page ranges as ``volume:pages``.
    match = re.search(r"[:：]\s*(?P<pages>[A-Za-z]?\d+\s*[–-]\s*[A-Za-z]?\d+)\s*$", text)
    if match:
        return normalize_space(match.group("pages"))
    return None


def _normalize_reference_venue(publication_info: str, year: str | None) -> str | None:
    venue = normalize_space(publication_info) or publication_info.strip()
    if year:
        venue = re.sub(rf"(?:[,;]?\s*){re.escape(year)}[a-z]?\s*$", "", venue).strip(" ,;.")
    venue = re.sub(
        r"[,;]?\s*\b(?:pp?\.?|pages?)\s*[A-Za-z]?\d+\s*[–-]\s*[A-Za-z]?\d+\s*$",
        "",
        venue,
        flags=re.IGNORECASE,
    ).strip(" ,;.")
    venue = re.sub(
        r"[,;]?\s*\b(?:pp?\.?|pages?)\s*[A-Za-z]?\d+\s*$",
        "",
        venue,
        flags=re.IGNORECASE,
    ).strip(" ,;.")
    venue = re.sub(r"[:：]\s*[A-Za-z]?\d+\s*[–-]\s*[A-Za-z]?\d+\s*$", "", venue).strip(" ,;.")
    return venue or None


def _select_reference_year_match(text: str) -> re.Match[str] | None:
    """Return the year token that should delimit reference front matter.

    References commonly appear in at least two shapes:

    - ``authors. 2020. title. venue`` (ACL-like author-year style)
    - ``authors. title. venue, 2020`` (trailing publication-year style)

    The previous implementation always used the first 4-digit year.  That
    breaks trailing-year references whose venue itself contains an event year,
    e.g. ``In Proceedings of the 2024 Joint International Conference ...,
    2024``: the venue was truncated to ``In Proceedings of the``.

    Keep the first year only when it is clearly the author-year marker;
    otherwise use the rightmost year as the bibliographic year delimiter.
    """
    matches = list(YEAR_RE.finditer(text))
    if not matches:
        return None
    if _is_author_year_reference(text, matches[0]):
        return matches[0]
    return matches[-1]


def _is_author_year_reference(text: str, year_match: re.Match[str]) -> bool:
    prefix = text[: year_match.start()]
    suffix = text[year_match.end() :]
    if not re.search(r"\.\s*$", prefix):
        return False
    if not re.match(r"\.?\s+\S", suffix):
        return False
    author_segment = prefix.rsplit(".", 1)[0].strip(" ,;")
    if not author_segment:
        return False
    lead = f"{author_segment}. {year_match.group(0)}."
    return _looks_like_unnumbered_reference_start(lead)


def _include_trailing_publication_year(
    text: str,
    venue: str,
    year_match: re.Match[str] | None,
) -> str:
    if year_match is None or _is_author_year_reference(text, year_match):
        return venue
    year = year_match.group(0)
    if re.search(rf"(?:^|[,\s]){re.escape(year)}\s*$", venue):
        return venue
    separator = "" if venue.endswith((",", ";")) else ","
    return normalize_space(f"{venue}{separator} {year}") or venue


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
