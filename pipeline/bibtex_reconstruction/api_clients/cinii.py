import re
from typing import Optional, Tuple
from api_clients.base_client import BaseAPIClient
from core import settings
from models import InputData, VerifiedCitationInfo

def _extract_field(raw_bibtex: str, field_name: str) -> Optional[str]:
    """
    Helper function to extract specific fields from a raw BibTeX string.
    
    Args:
        raw_bibtex (str): The full BibTeX string.
        field_name (str): The specific field to extract (e.g., 'doi', 'year').
        
    Returns:
        Optional[str]: The extracted value, or None if not found.
    """
    if not raw_bibtex: 
        return None
    pattern = rf"{field_name}\s*=\s*[{{|\"](.*?)[}}|\"]\s*(?:,|$)"
    match = re.search(pattern, raw_bibtex, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None

class CiNiiClient(BaseAPIClient):
    """Client for searching academic papers via the CiNii API."""

    @property
    def api_name(self) -> str:
        return "CiNii API"

    def search(self, input_data: InputData) -> Tuple[Optional[VerifiedCitationInfo], Optional[str]]:
        if not input_data.parsed_data or not input_data.parsed_data.title:
            return None, None
            
        search_title = input_data.parsed_data.title
        endpoint_url = f"{settings.cinii_base_url}/all"  

        params = {"title": search_title, "format": "json", "count": 1}
        if settings.cinii_appid:
            params["appid"] = settings.cinii_appid

        response = self._make_request(
            endpoint_url, 
            params=params, 
            timeout=settings.cinii_timeout
        )
        if not response:
            return None, None

        items = response.json().get("items", [])
        if not items:
            return None, None

        best_match = items[0]
                
        title = best_match.get("title", "")
        raw_authors = best_match.get("dc:creator", [])
        authors = raw_authors if isinstance(raw_authors, list) else [raw_authors]
        
        year = self._extract_year(best_match.get("prism:publicationDate", ""))
        venue = best_match.get("prism:publicationName", "")
        url = best_match.get("@id", "")
        
        doi = None
        for id_item in best_match.get("dc:identifier", [{}]):
            if id_item.get("@type") == "cir:DOI":
                doi = id_item.get("@value")
                break

        metadata = VerifiedCitationInfo(
            title=title, 
            authors=authors, 
            year=year, 
            venue=venue, 
            doi=doi, 
            url=url
        )

        raw_bibtex = self._fetch_bibtex_from_doi(doi, timeout=settings.crossref_timeout)
        
        if not raw_bibtex:
            crid_url = best_match.get("link", {}).get("@id", "")
            if crid_url:
                bib_resp = self._make_request(f"{crid_url}.bib", timeout=settings.cinii_timeout, max_retries=1)
                if bib_resp:
                    raw_bibtex = bib_resp.text
                    # The .bib file might contain a DOI that wasn't in the JSON response
                    extracted_doi = _extract_field(raw_bibtex, "doi")
                    if extracted_doi:
                        metadata.doi = extracted_doi

        if not raw_bibtex:
            raw_bibtex = self._generate_fallback_bibtex(metadata, "cinii")

        return metadata, raw_bibtex