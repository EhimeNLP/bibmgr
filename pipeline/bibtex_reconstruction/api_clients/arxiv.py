from typing import Optional, Tuple
from bs4 import BeautifulSoup
from api_clients.base_client import BaseAPIClient
from models import InputData, VerifiedCitationInfo

class ArxivClient(BaseAPIClient):
    """Client for searching academic papers via the arXiv API."""

    @property
    def api_name(self) -> str:
        return "arXiv API"

    @property
    def api_prefix(self) -> str:
        return "arxiv"

    def _execute_search(self, input_data: InputData) -> Tuple[Optional[VerifiedCitationInfo], Optional[str]]:
        search_query = f'ti:"{input_data.parsed_data.title}"'
        params = {"search_query": search_query, "start": 0, "max_results": 1}

        response = self._make_request(params=params)
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

        metadata = VerifiedCitationInfo(
            title=title, 
            authors=authors, 
            year=year, 
            venue=venue, 
            doi=doi, 
            url=url
        )

        return metadata, None