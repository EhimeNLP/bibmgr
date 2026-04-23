from typing import Optional, Tuple
from models.input_models import InputData
from models.output_models import Metadata
from api_clients.base_client import BaseAPIClient
from core.config import settings

class CrossrefClient(BaseAPIClient):
    @property
    def api_name(self) -> str:
        return "Crossref API"

    def search(self, input_data: InputData) -> Tuple[Optional[Metadata], Optional[str]]:
        if not input_data.parsed_data or not input_data.parsed_data.title:
            return None, None
            
        title = input_data.parsed_data.title
        params = {"query.title": title, "rows": 1}
        if settings.crossref_mailto:
            params["mailto"] = settings.crossref_mailto

        try:
            response = self._make_request(settings.crossref_base_url, params=params, timeout=settings.crossref_timeout)
            if not response: 
                return None, None

            items = response.json().get("message", {}).get("items", [])
            if not items: 
                return None, None 

            best_match = items[0]
            doi = best_match.get("DOI")
            
            if not doi: 
                return None, None

            title = best_match.get("title", [""])[0]
            authors = []
            for author in best_match.get("author", []):
                name = f"{author.get('given', '')} {author.get('family', '')}".strip()
                if name: 
                    authors.append(name)

            year = None
            date_parts = best_match.get("issued", {}).get("date-parts", [[]])
            if date_parts and date_parts[0]:
                year = date_parts[0][0]

            venue = best_match.get("container-title", [""])[0] if best_match.get("container-title") else None
            url = best_match.get("URL")

            metadata = Metadata(title=title, authors=authors, year=year, venue=venue, doi=doi, url=url)
            raw_bibtex = self._fetch_bibtex_from_doi(doi, timeout=settings.crossref_timeout)

            return metadata, raw_bibtex
        
        except Exception as e:
            print(f"[{self.api_name}] Error during search: {e}")
            return None, None