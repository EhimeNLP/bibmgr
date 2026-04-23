from typing import Optional, Tuple
from bs4 import BeautifulSoup
from models.input_models import InputData
from models.output_models import Metadata
from api_clients.base_client import BaseAPIClient
from core.config import settings

class ArxivClient(BaseAPIClient):
    @property
    def api_name(self) -> str:
        return "arXiv API"

    def search(self, input_data: InputData) -> Tuple[Optional[Metadata], Optional[str]]:
        if not input_data.parsed_data or not input_data.parsed_data.title:
            return None, None
            
        title = input_data.parsed_data.title
        search_query = f'ti:"{title}"'
        params = {"search_query": search_query, "start": 0, "max_results": 1}

        try:
            response = self._make_request(
                settings.arxiv_base_url, 
                params=params, 
                timeout=settings.arxiv_timeout
            )
            if not response:
                return None, None

            soup = BeautifulSoup(response.content, "xml")
            entry = soup.find("entry")

            if not entry:
                return None, None

            title = entry.find("title").get_text(strip=True) if entry.find("title") else ""
            title = " ".join(title.split())
            authors = [author.find("name").get_text(strip=True) for author in entry.find_all("author") if author.find("name")]
            published = entry.find("published").get_text(strip=True) if entry.find("published") else ""
            year = self._extract_year(published)
            journal_ref = entry.find("arxiv:journal_ref")
            venue = journal_ref.get_text(strip=True) if journal_ref else "arXiv"
            doi_tag = entry.find("arxiv:doi")
            doi = doi_tag.get_text(strip=True) if doi_tag else None
            url = entry.find("id").get_text(strip=True) if entry.find("id") else ""

            metadata = Metadata(title=title, authors=authors, year=year, venue=venue, doi=doi, url=url)

            raw_bibtex = self._fetch_bibtex_from_doi(doi)

            if not raw_bibtex:
                raw_bibtex = self._generate_fallback_bibtex(metadata, "arxiv")

            return metadata, raw_bibtex

        except Exception as e:
            print(f"[{self.api_name}] Error during search: {e}")
            return None, None