from typing import Optional, Tuple
from bs4 import BeautifulSoup
from api_clients.base_client import BaseAPIClient
from models import InputData, VerifiedCitationInfo

class JStageClient(BaseAPIClient):
    """Client for searching academic papers via the J-STAGE XML API."""

    @property
    def api_name(self) -> str:
        return "J-STAGE API"

    @property
    def api_prefix(self) -> str:
        return "jstage"

    def _execute_search(self, input_data: InputData) -> Tuple[Optional[VerifiedCitationInfo], Optional[str]]:
        params = {"service": 3, "article": input_data.parsed_data.title, "count": 1}
        
        response = self._make_request(params=params)
        if not response: 
            return None, None
            
        soup = BeautifulSoup(response.content, "xml")
        entries = soup.find_all("entry")
        if not entries: 
            return None, None

        best_match = entries[0]

        def get_text_safe(tag_name: str) -> str:
            tag = best_match.find(tag_name)
            if not tag: return ""
            ja_tag, en_tag = tag.find("ja"), tag.find("en")
            return (ja_tag.get_text(strip=True) if ja_tag else "") or (en_tag.get_text(strip=True) if en_tag else "")

        title = get_text_safe("article_title")
        venue = get_text_safe("material_title")
        url = get_text_safe("article_link")
        
        authors = []
        author_tag = best_match.find("author")
        if author_tag:
            ja_auth, en_auth = author_tag.find("ja"), author_tag.find("en")
            target_node = ja_auth if ja_auth and ja_auth.find("name") else en_auth
            if target_node:
                authors = [n.get_text(strip=True) for n in target_node.find_all("name") if n.get_text(strip=True)]

        pub_date_tag = best_match.find("pubyear")
        year = self._extract_year(pub_date_tag.get_text(strip=True)) if pub_date_tag else None
        
        doi_tag = best_match.find("prism:doi") or best_match.find("doi")
        doi = doi_tag.get_text(strip=True) if doi_tag else None
        
        metadata = VerifiedCitationInfo(
            title=title, 
            authors=authors, 
            year=year, 
            venue=venue, 
            doi=doi, 
            url=url
        )

        return metadata, None