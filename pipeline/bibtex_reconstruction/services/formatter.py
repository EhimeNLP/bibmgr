import re
from typing import Optional
from models import VerifiedCitationInfo
from core.llm_utils import extract_core_concept_via_llm
from core.bibtex_utils import extract_bibtex_field, extract_surname
from services.venue_resolver import VenueResolver


def apply_lab_rules(raw_bibtex: str, metadata: VerifiedCitationInfo, raw_text: str) -> str:
    """
    Applies laboratory-specific formatting rules to reconstruct a clean BibTeX string.
    Generates a custom BibTeX key using LLM, assigns abbreviations to the primary venue key,
    and preserves the formal name in a custom '_long' key.

    Args:
        raw_bibtex (str): The raw BibTeX string from the API, used for high-priority field extraction.
        metadata (VerifiedCitationInfo): The validated metadata containing fallback information.
        raw_text (str): The original text snippet of the reference, used for LLM concept extraction.

    Returns:
        str: The fully formatted BibTeX string conforming to the laboratory's standards.
    """
    if not metadata:
        return raw_bibtex or ""

    # 1. Extract fields (prioritize raw_bibtex if available, fallback to metadata)
    extracted_author = extract_bibtex_field(raw_bibtex, "author")
    authors = extracted_author or (" and ".join(metadata.authors) if metadata.authors else "unknown")

    title = extract_bibtex_field(raw_bibtex, "title") or metadata.title or "notitle"
    year = extract_bibtex_field(raw_bibtex, "year") or (str(metadata.year) if metadata.year else "unknown")
    url = extract_bibtex_field(raw_bibtex, "url") or metadata.url or ""
    volume = extract_bibtex_field(raw_bibtex, "volume")
    number = extract_bibtex_field(raw_bibtex, "number")
    pages = extract_bibtex_field(raw_bibtex, "pages")

    # Clean up page ranges (convert single hyphen to double hyphen for LaTeX)
    if pages:
        pages = re.sub(r'(?<!-)-(?!-)', '--', pages)

    raw_venue = (
        extract_bibtex_field(raw_bibtex, "journal")
        or extract_bibtex_field(raw_bibtex, "booktitle")
        or metadata.venue
        or ""
    )

    # 2. Resolve venue name and abbreviation.
    #    VenueResolver.resolve() always returns (formal_name, abbreviation | None).
    full_venue, abbrev = VenueResolver.resolve(raw_venue) if raw_venue else ("unknown", None)

    # 3. Determine entry type
    venue_lower = full_venue.lower()
    is_arxiv = "arxiv" in venue_lower or "arxiv" in (abbrev or "").lower()
    is_conference = not is_arxiv and any(
        k in venue_lower for k in ["proceedings", "conference", "symposium", "workshop", "大会", "研究会"]
    )

    entry_type = "inproceedings" if is_conference else "article"

    # 4. Generate laboratory-specific BibTeX key
    first_author_surname = extract_surname(metadata.authors[0] if metadata.authors else "")

    venue_str = re.sub(r'[^a-z0-9]', '', abbrev.lower()) if abbrev else "unknown"
    xx_str = extract_core_concept_via_llm(title, raw_text)
    xx_str_clean = re.sub(r'[^a-zA-Z0-9]', '', xx_str).lower() if xx_str else "unknown"

    bibtex_key = f"{first_author_surname}-{year}-{venue_str}-{xx_str_clean}"

    # 5. Construct the BibTeX string
    lines = []
    lines.append(f"@{entry_type}{{{bibtex_key},")
    lines.append(f"  title = {{{title}}},")
    lines.append(f"  author = {{{authors}}},")

    # arXiv entries
    if is_arxiv:
        arxiv_id = ""
        if url and "arxiv.org/abs/" in url:
            arxiv_id = url.split("arxiv.org/abs/")[-1].strip("/")
        else:
            match = re.search(r'arxiv:(\d+\.\d+)', raw_venue or "", re.IGNORECASE)
            if match:
                arxiv_id = match.group(1)
        journal_val = f"arXiv:{arxiv_id}" if arxiv_id else "arXiv"
        lines.append(f"  journal = {{{journal_val}}},")

    # Journal articles
    elif entry_type == "article":
        if abbrev:
            lines.append(f"  journal = {{{abbrev}}},")
            lines.append(f"  journal_long = {{{full_venue}}},")
        else:
            lines.append(f"  journal = {{{full_venue}}},")

        if volume: lines.append(f"  volume = {{{volume}}},")
        if number: lines.append(f"  number = {{{number}}},")
        if pages:  lines.append(f"  pages = {{{pages}}},")

    # Conference proceedings (with 'Proc. of' rule)
    elif entry_type == "inproceedings":
        if abbrev:
            lines.append(f"  booktitle = {{Proc. of {abbrev}}},")
            lines.append(f"  booktitle_long = {{{full_venue}}},")
        else:
            lines.append(f"  booktitle = {{{full_venue}}},")

        if pages: lines.append(f"  pages = {{{pages}}},")

    # Common trailing fields
    lines.append(f"  year = {{{year}}},")
    if url: lines.append(f"  url = {{{url}}},")
    lines.append("}")

    return "\n".join(lines)