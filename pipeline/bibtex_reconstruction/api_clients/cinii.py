import re
from typing import Optional, Tuple
from api_clients.base_client import BaseAPIClient
from core.config import settings
from models import InputData, VerifiedCitationInfo

def _extract_field(raw_bibtex: str, field_name: str) -> Optional[str]:
    """Helper function to extract specific fields from a raw BibTeX string."""
    if not raw_bibtex: return None
    pattern = rf"{field_name}\s*=\s*[{{|\"](.*?)[}}|\"]\s*(?:,|$)"
    match = re.search(pattern, raw_bibtex, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None

class CiNiiClient(BaseAPIClient):
    """Client for searching academic papers via the CiNii API."""

    @property
    def api_name(self) -> str:
        return "CiNii API"

    @property
    def api_prefix(self) -> str:
        return "cinii"

    def _execute_search(self, input_data: InputData) -> Tuple[Optional[VerifiedCitationInfo], Optional[str]]:
        endpoint_url = f"{self.base_url}/all"  

        params = {"title": input_data.parsed_data.title, "format": "json", "count": 1}
        if settings.cinii_appid:
            params["appid"] = settings.cinii_appid

        response = self._make_request(url=endpoint_url, params=params)
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

        custom_bibtex = None
        crid_url = best_match.get("link", {}).get("@id", "")
        
        if crid_url:
            bib_resp = self._make_request(url=f"{crid_url}.bib")
            if bib_resp:
                custom_bibtex = bib_resp.text
                extracted_doi = _extract_field(custom_bibtex, "doi")
                if extracted_doi:
                    metadata.doi = extracted_doi

        return metadata, custom_bibtex