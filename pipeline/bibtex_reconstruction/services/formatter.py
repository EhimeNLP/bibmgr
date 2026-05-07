import re
from typing import Tuple, Optional
from models import VerifiedCitationInfo
from core.llm_utils import extract_core_concept_via_llm
from services.venue_resolver import VenueResolver

def _extract_field(raw_bibtex: str, field_name: str) -> Optional[str]:
    """
    Extracts a specific field's value from a raw BibTeX string.

    Args:
        raw_bibtex (str): The raw BibTeX string retrieved from an external API.
        field_name (str): The name of the BibTeX field to extract (e.g., 'author', 'title').

    Returns:
        Optional[str]: The extracted value without braces/quotes, or None if not found.
    """
    if not raw_bibtex: return None
    pattern = rf"{field_name}\s*=\s*[{{|\"](.*?)[}}|\"]\s*(?:,|$)"
    match = re.search(pattern, raw_bibtex, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None

def _resolve_venue_info(venue_full_name: str) -> Tuple[str, Optional[str]]:
    """
    Resolves the formal venue name and its abbreviation using the VenueResolver.

    Args:
        venue_full_name (str): The formal name of the venue (e.g., conference or journal name).

    Returns:
        Tuple[str, Optional[str]]: A tuple containing the formal venue name and its resolved abbreviation. 
        If no abbreviation is found, the second element is None.
    """
    if not venue_full_name:
        return "unknown", None
    
    abbrev = VenueResolver.resolve(venue_full_name)
    
    if abbrev == venue_full_name:
        return venue_full_name, None
        
    return venue_full_name, abbrev

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
    authors = _extract_field(raw_bibtex, "author") or " and ".join(metadata.authors) if metadata.authors else "unknown"
    title = _extract_field(raw_bibtex, "title") or metadata.title
    year = _extract_field(raw_bibtex, "year") or str(metadata.year)
    url = _extract_field(raw_bibtex, "url") or metadata.url or ""
    volume = _extract_field(raw_bibtex, "volume")
    number = _extract_field(raw_bibtex, "number")
    pages = _extract_field(raw_bibtex, "pages")
    
    # Clean up page ranges (convert single hyphen to double hyphen for LaTeX)
    if pages:
        pages = re.sub(r'(?<!-)-(?!-)', '--', pages)

    raw_venue = _extract_field(raw_bibtex, "journal") or _extract_field(raw_bibtex, "booktitle") or metadata.venue
    
    # 2. Resolve Venue Name and Abbreviation
    full_venue, abbrev = _resolve_venue_info(raw_venue)

    # 3. Determine Entry Type
    venue_lower = full_venue.lower()
    is_arxiv = "arxiv" in venue_lower or "arxiv" in (abbrev or "").lower()
    is_conference = not is_arxiv and any(k in venue_lower for k in ["proceedings", "conference", "symposium", "workshop", "大会", "研究会"])
    
    entry_type = "inproceedings" if is_conference else "article"

    # 4. Generate Laboratory-Specific BibTeX Key
    first_author_surname = "unknown"
    if metadata.authors:
        first_author_surname = metadata.authors[0].split(",")[0].split()[-1].lower()
        first_author_surname = re.sub(r'[^a-z0-9]', '', first_author_surname)

    venue_str = (abbrev or full_venue or "unknown").lower().replace(" ", "")
    venue_str = re.sub(r'[^a-z0-9]', '', venue_str)
    
    xx_str = extract_core_concept_via_llm(title, raw_text)
    xx_str_clean = re.sub(r'[^a-zA-Z0-9]', '', xx_str).lower() if xx_str else "unknown"

    bibtex_key = f"{first_author_surname}-{year}-{venue_str}-{xx_str_clean}"

    # 5. Construct the BibTeX String
    lines = []
    lines.append(f"@{entry_type}{{{bibtex_key},")
    lines.append(f"  title = {{{title}}},")
    lines.append(f"  author = {{{authors}}},")

    # Format arXiv entries
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
        
    # Format Journal articles
    elif entry_type == "article":
        if abbrev:
            lines.append(f"  journal = {{{abbrev}}},")
            lines.append(f"  journal_long = {{{full_venue}}},")
        else:
            lines.append(f"  journal = {{{full_venue}}},")
            
        if volume: lines.append(f"  volume = {{{volume}}},")
        if number: lines.append(f"  number = {{{number}}},")
        if pages:  lines.append(f"  pages = {{{pages}}},")
        
    # Format Conference proceedings (with 'Proc. of' rule)
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