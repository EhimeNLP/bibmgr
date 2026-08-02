"""Small BibTeX field extraction helpers."""

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Optional

import bibtexparser
import bibmgr_native
from bibtexparser.model import Entry, Field


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BibtexInspection:
    """Deterministic quality result for one BibTeX entry."""

    parsed: bool
    entry_type: str | None
    citation_key: str | None
    missing_fields: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return self.parsed and not self.missing_fields


_TYPE_SPECIFIC_REQUIRED_FIELDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "article": (("journal",),),
    "inproceedings": (("booktitle",),),
    "conference": (("booktitle",),),
    "incollection": (("booktitle",),),
    "inbook": (("booktitle",),),
    "phdthesis": (("school",),),
    "mastersthesis": (("school",),),
    "techreport": (("institution",),),
}

_PORTABLE_BIBTEX_FIELDS = {
    "abstract",
    "address",
    "author",
    "booktitle",
    "chapter",
    "doi",
    "editor",
    "eprint",
    "howpublished",
    "institution",
    "isbn",
    "issn",
    "journal",
    "month",
    "note",
    "number",
    "organization",
    "pages",
    "primaryclass",
    "publisher",
    "school",
    "series",
    "title",
    "type",
    "url",
    "volume",
    "year",
}


def inspect_bibtex(raw_bibtex: str) -> BibtexInspection:
    """Check whether one entry contains its core bibliographic identity."""

    if not raw_bibtex:
        return BibtexInspection(False, None, None, ("parseable_entry",))
    try:
        library = bibtexparser.parse_string(raw_bibtex)
    except Exception as exc:
        logger.debug(
            "BibTeX quality inspection failed error_type=%s",
            exc.__class__.__name__,
        )
        return BibtexInspection(False, None, None, ("parseable_entry",))
    if len(library.entries) != 1 or library.failed_blocks:
        return BibtexInspection(False, None, None, ("single_parseable_entry",))

    entry = library.entries[0]
    fields = {
        key.casefold(): field.value.strip()
        for key, field in entry.fields_dict.items()
        if field.value is not None
    }
    missing: list[str] = []
    if not fields.get("title"):
        missing.append("title")
    if not fields.get("author") and not fields.get("editor"):
        missing.append("author_or_editor")
    if not fields.get("year"):
        missing.append("year")

    entry_type = entry.entry_type.casefold()
    for alternatives in _TYPE_SPECIFIC_REQUIRED_FIELDS.get(entry_type, ()):
        if not any(fields.get(field_name) for field_name in alternatives):
            missing.append("_or_".join(alternatives))

    return BibtexInspection(
        parsed=True,
        entry_type=entry_type,
        citation_key=entry.key,
        missing_fields=tuple(missing),
    )


def bibtex_fields(raw_bibtex: str) -> dict[str, str]:
    """Return the first entry's non-empty fields with case-folded names."""

    if not raw_bibtex:
        return {}
    try:
        library = bibtexparser.parse_string(raw_bibtex)
    except Exception:
        return {}
    if len(library.entries) != 1 or library.failed_blocks:
        return {}
    return {
        key.casefold(): field.value.strip()
        for key, field in library.entries[0].fields_dict.items()
        if field.value is not None and field.value.strip()
    }


def replace_bibtex_citation_key(
    raw_bibtex: str,
    replacement: str,
) -> str:
    """Replace only the entry key while preserving every field byte."""

    inspection = inspect_bibtex(raw_bibtex)
    if not inspection.parsed or not inspection.citation_key or not replacement:
        return raw_bibtex
    pattern = re.compile(
        r"(@\s*[a-zA-Z][\w-]*\s*[({]\s*)"
        + re.escape(inspection.citation_key)
        + r"(?=\s*,)",
    )
    return pattern.sub(
        lambda match: match.group(1) + replacement,
        raw_bibtex,
        count=1,
    )


def fill_missing_bibtex_fields(
    raw_bibtex: str,
    field_sources: Iterable[Mapping[str, str | None]],
) -> tuple[str, list[str]]:
    """Fill empty fields without overwriting information already present."""

    try:
        library = bibtexparser.parse_string(raw_bibtex)
    except Exception:
        return raw_bibtex, []
    if len(library.entries) != 1 or library.failed_blocks:
        return raw_bibtex, []

    entry = library.entries[0]
    present = {
        key.casefold(): field.value.strip()
        for key, field in entry.fields_dict.items()
        if field.value is not None
    }
    filled: list[str] = []
    for source in field_sources:
        for raw_name, raw_value in source.items():
            name = raw_name.casefold()
            if (
                name not in _PORTABLE_BIBTEX_FIELDS
                or raw_value is None
                or not str(raw_value).strip()
                or present.get(name)
            ):
                continue
            value = str(raw_value).strip()
            existing_key = next(
                (
                    key
                    for key in entry.fields_dict
                    if key.casefold() == name
                ),
                name,
            )
            entry.set_field(Field(existing_key, value))
            present[name] = value
            filled.append(name)

    if not filled:
        return raw_bibtex, []
    return bibtexparser.write_string(library).strip(), filled


def insert_missing_bibtex_fields(
    raw_bibtex: str,
    field_source: Mapping[str, str | None],
) -> tuple[str, list[str]]:
    """Insert fields into the original CST without rewriting existing text.

    Exactly one supplement mapping is accepted so a final entry cannot become
    an untraceable hybrid assembled from several providers.
    """

    inspection = inspect_bibtex(raw_bibtex)
    if not inspection.parsed:
        return raw_bibtex, []
    present = bibtex_fields(raw_bibtex)
    additions: list[tuple[str, str]] = []
    for raw_name, raw_value in field_source.items():
        name = raw_name.casefold()
        value = str(raw_value).strip() if raw_value is not None else ""
        if (
            name in _PORTABLE_BIBTEX_FIELDS
            and value
            and not present.get(name)
        ):
            additions.append((name, value))
            present[name] = value
    if not additions:
        return raw_bibtex, []

    # Empty fields are present in the CST but absent semantically. Replace only
    # their value token before inserting truly absent fields.
    empty_edits: list[tuple[int, int, str, str]] = []
    remaining: list[tuple[str, str]] = []
    for name, value in additions:
        match = re.search(
            rf"(?im)(^\s*{re.escape(name)}\s*=\s*)"
            r"(\{\s*\}|\"\s*\")",
            raw_bibtex,
        )
        if match is None:
            remaining.append((name, value))
            continue
        start = len(raw_bibtex[:match.start(2)].encode("utf-8"))
        end = len(raw_bibtex[:match.end(2)].encode("utf-8"))
        empty_edits.append((start, end, f"{{{value}}}", name))
    if empty_edits:
        session = bibmgr_native.DocumentSession(
            raw_bibtex,
            profile="modern",
            tolerant=True,
        )
        for start, end, replacement, _name in sorted(
            empty_edits,
            reverse=True,
        ):
            session.update(
                session.analysis.source_revision,
                bibmgr_native.TextEdit(start, end, replacement),
            )
        updated = session.source
        if not remaining:
            return updated, [item[3] for item in empty_edits]
        inserted, inserted_names = insert_missing_bibtex_fields(
            updated,
            dict(remaining),
        )
        return (
            inserted,
            [item[3] for item in empty_edits] + inserted_names,
        )

    analysis = bibmgr_native.analyze(
        raw_bibtex,
        profile="modern",
        tolerant=True,
    )
    records = analysis.bibliography.get("records", [])
    if len(records) != 1:
        return raw_bibtex, []
    entry_origin = next(
        (
            origin
            for origin in records[0].get("origins", [])
            if origin.get("kind") == "entry"
        ),
        None,
    )
    if entry_origin is None:
        return raw_bibtex, []

    source_bytes = raw_bibtex.encode("utf-8")
    entry_end = int(entry_origin["range"]["end"])
    close_index = entry_end - 1
    if close_index < 0 or source_bytes[close_index:entry_end] not in {
        b"}",
        b")",
    }:
        return raw_bibtex, []
    insert_at = close_index
    while (
        insert_at > 0
        and source_bytes[insert_at - 1:insert_at].isspace()
    ):
        insert_at -= 1
    comma = (
        ""
        if source_bytes[max(0, insert_at - 1):insert_at] == b","
        else ","
    )
    replacement = comma + "".join(
        f"\n  {name} = {{{value}}},"
        for name, value in additions
    )
    session = bibmgr_native.DocumentSession(
        raw_bibtex,
        profile="modern",
        tolerant=True,
    )
    session.update(
        session.analysis.source_revision,
        bibmgr_native.TextEdit(insert_at, insert_at, replacement),
    )
    return session.source, [name for name, _ in additions]


def metadata_bibtex_fields(
    *,
    entry_type: str | None,
    title: str | None,
    authors: Iterable[str],
    year: int | None,
    venue: str | None,
    publisher: str | None = None,
    volume: str | None = None,
    number: str | None = None,
    pages: str | None = None,
    doi: str | None = None,
    url: str | None = None,
) -> dict[str, str]:
    """Map verified metadata into fields appropriate for the entry type."""

    result: dict[str, str] = {}
    if title:
        result["title"] = title
    author_list = [author.strip() for author in authors if author.strip()]
    if author_list:
        result["author"] = " and ".join(author_list)
    if year is not None:
        result["year"] = str(year)
    if venue:
        if entry_type == "article":
            result["journal"] = venue
        elif entry_type in {
            "conference",
            "inbook",
            "incollection",
            "inproceedings",
        }:
            result["booktitle"] = venue
    if publisher:
        result["publisher"] = publisher
    if volume:
        result["volume"] = volume
    if number:
        result["number"] = number
    if pages:
        result["pages"] = pages
    if doi:
        result["doi"] = doi
    if url:
        result["url"] = url
    return result


def render_metadata_bibtex(
    *,
    entry_type: str,
    citation_key: str,
    fields: Mapping[str, str],
) -> str:
    """Serialize one new entry assembled from explicitly sourced metadata."""

    portable = [
        Field(name.casefold(), str(value).strip())
        for name, value in fields.items()
        if (
            name.casefold() in _PORTABLE_BIBTEX_FIELDS
            and str(value).strip()
        )
    ]
    library = bibtexparser.Library()
    library.add(Entry(entry_type, citation_key, portable))
    return bibtexparser.write_string(library).strip()


def extract_bibtex_field(raw_bibtex: str, field_name: str) -> Optional[str]:
    """
    Extract the value of *field_name* from a raw BibTeX string using bibtexparser v2.

    This library-based implementation natively handles:
        - Nested quotes and braces  (e.g., title = {{BERT}: Pre-training ...})
        - Comment lines starting with '%'
        - @string macros

    bibtexparser v2 preserves the original case of field keys, so the lookup is
    performed case-insensitively to match both ``title`` and ``TITLE``.

    Args:
        raw_bibtex (str): Raw BibTeX string from an external API.
        field_name (str): Field name to extract (e.g. 'title', 'author').

    Returns:
        Optional[str]: Field value with outer delimiters stripped,
                       or None if the field is not found.
    """
    if not raw_bibtex:
        return None

    try:
        library = bibtexparser.parse_string(raw_bibtex)

        if not library.entries:
            return None

        entry = library.entries[0]

        target = field_name.lower()
        for key, field in entry.fields_dict.items():
            if key.lower() == target:
                return field.value.strip() if field.value else None

        return None

    except Exception as exc:
        logger.debug(
            "BibTeX field extraction failed field=%s error_type=%s",
            field_name,
            exc.__class__.__name__,
        )
        return None

_CJK_RE = re.compile(
    r"["
    r"\u3040-\u309f"           # 平仮名
    r"\u30a0-\u30ff"           # 片仮名
    r"\u31f0-\u31ff"           # 片仮名拡張
    r"\u3130-\u318f"           # ハングル互換字母
    r"\uac00-\ud7a3"           # ハングル音節文字
    r"\u4e00-\u9ffc"           # CJK統合漢字
    r"\u3400-\u4dbf"           # CJK統合漢字拡張A
    r"\uf900-\ufaff"           # CJK互換漢字
    r"\U00020000-\U0002a6df"   # CJK統合漢字拡張B
    r"]"
)

def _contains_cjk(text: str) -> bool:
    """Return True if *text* contains any CJK, Kana, or Hangul character."""
    return bool(_CJK_RE.search(text))

_NOBILIARY_PARTICLES = {"von", "van", "de", "di", "da", "del", "du", "le"}

def extract_surname(author: str) -> str:
    """
    Extract a BibTeX-key-safe surname from a single author string.

    Handles three formats:
        - Roman, family-first  : "Yamada, Taro"          → "yamada"
        - Roman, given-first   : "Taro Yamada"            → "yamada"
        - Given + particle     : "Ludwig van Beethoven"   → "vanbeethoven"
        - CJK (Japanese/Korean): "山田 太郎"               → "山田"

    Args:
        author (str): A single author name string.

    Returns:
        str: Surname suitable for use in a BibTeX key, or "unknown" if empty.
    """
    if not author:
        return "unknown"

    # 1. CJK-based names: surname is the first whitespace-delimited token
    if _contains_cjk(author):
        surname = author.strip().split()[0]
        return surname if surname else "unknown"

    # 2. Roman names: "Family, Given" format
    if "," in author:
        surname = author.split(",")[0].strip().lower()
        return re.sub(r"[^a-z0-9]", "", surname) or "unknown"

    # 3. Roman names: "Given [Particle] Family" format
    parts = author.strip().split()
    if parts:
        if len(parts) > 2 and parts[-2].lower() in _NOBILIARY_PARTICLES:
            # e.g. "Ludwig van Beethoven" → "vanbeethoven"
            surname = "".join(parts[-2:]).lower()
        else:
            surname = parts[-1].lower()
    else:
        surname = ""

    return re.sub(r"[^a-z0-9]", "", surname) or "unknown"
