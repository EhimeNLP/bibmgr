import re
from typing import Tuple, Optional
from models import VerifiedCitationInfo
from core import settings
from core.llm_utils import extract_core_concept_via_llm

def _extract_field(raw_bibtex: str, field_name: str) -> Optional[str]:
    if not raw_bibtex: return None
    pattern = rf"{field_name}\s*=\s*[{{|\"](.*?)[}}|\"]\s*(?:,|$)"
    match = re.search(pattern, raw_bibtex, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None

def _get_abbreviation(venue_full_name: str) -> Tuple[Optional[str], Optional[str]]:
    if not venue_full_name: return None, None
    venue_lower = venue_full_name.lower()
    
    if "arxiv" in venue_lower:
        return "arXiv", venue_full_name

    extracted_abbrev = None
    match = re.search(r'\(([A-Za-z0-9\-]+)\)', venue_full_name)
    if match:
        candidate = match.group(1)
        if any(c.isupper() for c in candidate) and not candidate.isdigit():
            extracted_abbrev = candidate

    dict_abbrev = None
    sorted_venues = sorted(settings.venue_abbrev_map.items(), key=lambda x: len(x[0]), reverse=True)    
    for key, abbrev in sorted_venues:
        if key in venue_lower:
            dict_abbrev = abbrev
            break
            
    final_abbrev = extracted_abbrev or dict_abbrev
    
    return final_abbrev, venue_full_name

def apply_lab_rules(raw_bibtex: str, metadata: VerifiedCitationInfo, raw_text: str, current_status: str) -> Tuple[str, str]:
    if not raw_bibtex or not metadata:
        return raw_bibtex, current_status

    status = current_status

    authors = _extract_field(raw_bibtex, "author") or " and ".join(metadata.authors)
    title = _extract_field(raw_bibtex, "title") or metadata.title
    year = _extract_field(raw_bibtex, "year") or str(metadata.year)
    url = _extract_field(raw_bibtex, "url") or metadata.url or ""
    volume = _extract_field(raw_bibtex, "volume")
    number = _extract_field(raw_bibtex, "number")
    pages = _extract_field(raw_bibtex, "pages")
    
    if pages:
        pages = re.sub(r'(?<!-)-(?!-)', '--', pages)

    raw_venue = _extract_field(raw_bibtex, "journal") or _extract_field(raw_bibtex, "booktitle") or metadata.venue
    abbrev, full_venue = _get_abbreviation(raw_venue)

    is_arxiv = (abbrev == "arXiv")
    known_conferences = [v for v in settings.venue_abbrev_map.values() if v != "arXiv"]
    
    is_conference = not is_arxiv and (
        "conference" in (raw_venue or "").lower() or 
        "proceedings" in (raw_venue or "").lower() or 
        "workshop" in (raw_venue or "").lower() or
        abbrev in known_conferences or
        (abbrev and abbrev != "arXiv")
    )
    
    entry_type = "inproceedings" if is_conference else "article"

    first_author_surname = "unknown"
    if metadata.authors:
        first_author_surname = metadata.authors[0].split(",")[0].split()[-1].lower()

    venue_str = (abbrev or "unknown").lower().replace(" ", "")
    
    xx_str = extract_core_concept_via_llm(title, raw_text)
    
    bibtex_key = f"{first_author_surname}-{year}-{venue_str}-{xx_str}"

    if venue_str == "unknown" or xx_str == "unknown":
        status = "needs_review"

    lines = []
    lines.append(f"@{entry_type}{{{bibtex_key},")
    
    # 共通ヘッダー (title -> author)
    lines.append(f"    title = {{{{{title}}}}},")
    lines.append(f"    author = \"{authors}\",")

    # arXiv の場合 (title -> author -> journal -> year -> url)
    if is_arxiv:
        arxiv_id = ""
        if url and "arxiv.org/abs/" in url:
            arxiv_id = url.split("arxiv.org/abs/")[-1].strip("/")
        else:
            match = re.search(r'arxiv:(\d+\.\d+)', raw_venue or "", re.IGNORECASE)
            if match:
                arxiv_id = match.group(1)
        
        journal_val = f"arXiv:{arxiv_id}" if arxiv_id else "arXiv"
        lines.append(f"    journal = \"{journal_val}\",")

    # 論文誌 の場合 (title -> author -> journal -> volume -> number -> pages -> year -> url)
    elif entry_type == "article":
        if abbrev and full_venue and abbrev != full_venue:
            lines.append(f"    journal = \"{abbrev}\",")      # 略称を上に置く
            lines.append(f"    journal = \"{full_venue}\",") # 正式名称を下に置く
        else:
            lines.append(f"    journal = \"{full_venue or abbrev}\",")
            
        if volume: lines.append(f"    volume = \"{volume}\",")
        if number: lines.append(f"    number = \"{number}\",")
        if pages:  lines.append(f"    pages = \"{pages}\",")
        

    # 国際会議 の場合 (title -> author -> booktitle -> pages -> year -> url)
    elif entry_type == "inproceedings":
        if abbrev and full_venue and abbrev != full_venue:
            lines.append(f"    booktitle = \"Proc. of {abbrev}\",") # 略称を上に置く
            lines.append(f"    booktitle = \"{full_venue}\",")      # 正式名称を下に置く
        else:
            display_venue = full_venue or abbrev
            lines.append(f"    booktitle = \"{display_venue}\",")
            
        if pages: lines.append(f"    pages = \"{pages}\",")
        

    # 終端 (year -> url)
    lines.append(f"    year = \"{year}\",")
    if url:    lines.append(f"    url = \"{url}\",")
    lines.append("}")

    formatted_bibtex = "\n".join(lines)
    return formatted_bibtex, status