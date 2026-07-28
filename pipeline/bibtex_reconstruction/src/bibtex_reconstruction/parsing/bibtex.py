"""Small BibTeX field extraction helpers."""

import re
from typing import Optional
import bibtexparser

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

    except Exception as e:
        print(f"[BibTeX Parser] Error parsing raw string: {e}")
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
