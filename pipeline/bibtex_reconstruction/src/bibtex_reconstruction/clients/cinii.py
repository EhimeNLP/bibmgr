from typing import Optional, Tuple
from ..config import settings
from ..domain import InputData, VerifiedCitationInfo
from ..parsing.bibtex import extract_bibtex_field
from .base import BaseAPIClient

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

        response = self._make_request(
            url=endpoint_url,
            params=params,
            operation="metadata_search",
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

        custom_bibtex = None
        link = best_match.get("link", {})
        if isinstance(link, list):
            crid_url = link[0].get("@id", "") if link else ""
        elif isinstance(link, dict):
            crid_url = link.get("@id", "")
        else:
            crid_url = ""

        if crid_url:
            bib_resp = self._make_request(
                url=f"{crid_url}.bib",
                operation="citation_export",
                required=False,
            )
            if bib_resp:
                custom_bibtex = bib_resp.text
                extracted_doi = extract_bibtex_field(custom_bibtex, "doi")
                if extracted_doi:
                    metadata.doi = extracted_doi

        return metadata, custom_bibtex
