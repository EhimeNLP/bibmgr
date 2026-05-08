import re
from typing import Optional

def extract_bibtex_field(raw_bibtex: str, field_name: str) -> Optional[str]:
    """
    Extract the value of *field_name* from a raw BibTeX string.

    Correctly handles all standard BibTeX delimiter patterns:
        field = {single braces}
        field = {{double braces}}          ← title-case protection
        field = {{BERT}: Pre-training ...} ← partial double braces
        field = "double quotes"

    The outer delimiter layer is stripped so callers always receive the
    bare content.  Inner braces used for title-case protection are
    preserved (e.g. "{{BERT}: Pre-training ...}" → "{BERT}: Pre-training ...").

    Args:
        raw_bibtex (str): Raw BibTeX string from an external API.
        field_name (str): Field name to extract (e.g. 'title', 'author').

    Returns:
        Optional[str]: Field value with outer delimiters stripped,
                       or None if the field is not found.
    """
    if not raw_bibtex:
        return None

    # Locate "field_name \s* =" and find the start of the value.
    header = re.search(
        rf"{re.escape(field_name)}\s*=\s*",
        raw_bibtex,
        re.IGNORECASE,
    )
    if not header:
        return None

    pos = header.end()
    if pos >= len(raw_bibtex):
        return None

    # --- Brace-delimited value ---
    if raw_bibtex[pos] == '{':
        depth = 0
        start = pos  # points at the opening '{'
        i = pos
        while i < len(raw_bibtex):
            ch = raw_bibtex[i]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    # raw_bibtex[start:i+1] is the full "{...}" span.
                    # Strip exactly one outer brace layer.
                    inner = raw_bibtex[start + 1 : i]
                    return inner.strip()
            i += 1
        return None  # unmatched brace — malformed BibTeX

    # --- Quote-delimited value ---
    if raw_bibtex[pos] == '"':
        end = raw_bibtex.find('"', pos + 1)
        if end == -1:
            return None
        return raw_bibtex[pos + 1 : end].strip()

    return None


_CJK_RE = re.compile(r'[\u3000-\u9fff\uf900-\ufaff]')


def _is_japanese(text: str) -> bool:
    """Return True if *text* contains any CJK / Kana character."""
    return bool(_CJK_RE.search(text))


def extract_surname(author: str) -> str:
    """
    Extract a BibTeX-key-safe surname from a single author string.

    Handles three formats:
        - Roman, family-first  : "Yamada, Taro"   → "yamada"
        - Roman, given-first   : "Taro Yamada"     → "yamada"
        - Japanese (CJK)       : "山田 太郎"        → "山田"  (kept as-is)

    If the result contains only ASCII alphanumerics it is lowercased.
    Japanese surnames are returned unchanged so BibTeX keys remain readable
    (e.g. "山田-2024-acl-llm") rather than degrading to "unknown".

    Args:
        author (str): A single author name string.

    Returns:
        str: Surname suitable for use in a BibTeX key, or "unknown" if empty.
    """
    if not author:
        return "unknown"

    # Japanese name: surname is the first whitespace-delimited token.
    if _is_japanese(author):
        surname = author.strip().split()[0]
        return surname if surname else "unknown"

    # Roman name: "Family, Given" format.
    if "," in author:
        surname = author.split(",")[0].strip().lower()
        return re.sub(r'[^a-z0-9]', '', surname) or "unknown"

    # Roman name: "Given Family" format — take the last token as surname.
    parts = author.strip().split()
    surname = parts[-1].lower() if parts else ""
    return re.sub(r'[^a-z0-9]', '', surname) or "unknown"
