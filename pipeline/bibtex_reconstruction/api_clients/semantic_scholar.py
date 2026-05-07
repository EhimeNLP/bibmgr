from typing import Optional, Tuple
from api_clients.base_client import BaseAPIClient
from core.config import settings
from models import InputData, VerifiedCitationInfo

class SemanticScholarClient(BaseAPIClient):
    """Client for searching academic papers via the Semantic Scholar REST API."""

    @property
    def api_name(self) -> str:
        return "Semantic Scholar API"

    @property
    def api_prefix(self) -> str:
        return "semanticscholar"

    def _execute_search(self, input_data: InputData) -> Tuple[Optional[VerifiedCitationInfo], Optional[str]]:
        headers = {"x-api-key": settings.semanticscholar_api_key} if settings.semanticscholar_api_key else {}
        params = {
            "query": input_data.parsed_data.title, 
            "limit": 1, 
            "fields": "title,authors,year,venue,externalIds,url"
        }
        
        response = self._make_request(params=params, headers=headers)
        if not response:
            return None, None

        data = response.json().get("data", [])
        if not data:
            return None, None

        best_match = data[0]
        metadata = VerifiedCitationInfo(
            title=best_match.get("title", ""), 
            authors=[a.get("name", "") for a in best_match.get("authors", []) if "name" in a], 
            year=best_match.get("year"), 
            venue=best_match.get("venue", ""), 
            doi=best_match.get("externalIds", {}).get("DOI"), 
            url=best_match.get("url", "")
        )

        return metadata, None