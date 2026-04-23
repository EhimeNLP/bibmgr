from typing import Optional, Tuple
from models.input_models import InputData
from models.output_models import Metadata
from api_clients.base_client import BaseAPIClient
from core.config import settings

class SemanticScholarClient(BaseAPIClient):
    @property
    def api_name(self) -> str:
        return "Semantic Scholar API"

    def search(self, input_data: InputData) -> Tuple[Optional[Metadata], Optional[str]]:
        if not input_data.parsed_data or not input_data.parsed_data.title:
            return None, None
            
        title = input_data.parsed_data.title
        headers = {"x-api-key": settings.s2_api_key} if settings.s2_api_key else {}
        params = {"query": title, "limit": 1, "fields": "title,authors,year,venue,externalIds,url"}
        try:
            response = self._make_request(
                settings.s2_base_url, 
                params=params,
                headers=headers, 
                timeout=settings.s2_timeout
            )
            if not response:
                return None, None

            items = response.json().get("data", [])
            if not items:
                return None, None

            best_match = items[0]
            
            title = best_match.get("title", "")
            authors = [author.get("name", "") for author in best_match.get("authors", []) if "name" in author]
            year = best_match.get("year")
            venue = best_match.get("venue", "")
            url = best_match.get("url", "")
            doi = best_match.get("externalIds", {}).get("DOI")

            metadata = Metadata(title=title, authors=authors, year=year, venue=venue, doi=doi, url=url)

            raw_bibtex = self._fetch_bibtex_from_doi(doi, timeout=settings.s2_timeout)
            if not raw_bibtex:
                raw_bibtex = self._generate_fallback_bibtex(metadata, "s2")

            return metadata, raw_bibtex
        except Exception as e:
            print(f"[{self.api_name}] Error during search: {e}")
            return None, None