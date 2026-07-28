from typing import Optional, Tuple
from ..config import settings
from ..domain import InputData, VerifiedCitationInfo
from .base import BaseAPIClient

class CrossrefClient(BaseAPIClient):
    """Client for searching academic papers via the Crossref REST API."""

    @property
    def api_name(self) -> str:
        return "Crossref API"

    @property
    def api_prefix(self) -> str:
        return "crossref"

    def _execute_search(self, input_data: InputData) -> Tuple[Optional[VerifiedCitationInfo], Optional[str]]:
        params = {"query.title": input_data.parsed_data.title, "rows": 1}
        if settings.crossref_mailto:
            params["mailto"] = settings.crossref_mailto

        response = self._make_request(params=params)
        if not response: 
            return None, None

        items = response.json().get("message", {}).get("items", [])
        if not items: 
            return None, None 

        best_match = items[0]
        doi = best_match.get("DOI")
        
        # Crossref relies heavily on DOI. If not found, it's a weak match.
        if not doi: 
            return None, None

        title_list = best_match.get("title", [])
        title = title_list[0] if title_list else ""
        
        authors = []
        for author in best_match.get("author", []):
            name = f"{author.get('given', '')} {author.get('family', '')}".strip()
            if name: 
                authors.append(name)

        year = None
        date_parts = best_match.get("issued", {}).get("date-parts", [[]])
        if date_parts and date_parts[0]:
            year = date_parts[0][0]

        venue = best_match.get("container-title", [""])[0] if best_match.get("container-title") else ""
        url = best_match.get("URL", "")

        metadata = VerifiedCitationInfo(
            title=title, 
            authors=authors, 
            year=year, 
            venue=venue, 
            doi=doi, 
            url=url
        )
        
        return metadata, None
