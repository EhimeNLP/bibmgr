from typing import Optional, Tuple
from bs4 import BeautifulSoup
from api_clients.base_client import BaseAPIClient
from core import settings
from models import InputData, VerifiedCitationInfo

class JStageClient(BaseAPIClient):
    """Client for searching academic papers via the J-STAGE XML API."""

    @property
    def api_name(self) -> str:
        return "J-STAGE API"

    def search(self, input_data: InputData) -> Tuple[Optional[VerifiedCitationInfo], Optional[str]]:
        """
        Searches the J-STAGE API for a given reference using its title.
        
        Args:
            input_data (InputData): The envelope containing the parsed reference data.
            
        Returns:
            Tuple[Optional[VerifiedCitationInfo], Optional[str]]: 
            A tuple containing the verified metadata and BibTeX string, or (None, None) if not found.
        """
        if not input_data.parsed_data or not input_data.parsed_data.title:
            return None, None
            
        search_title = input_data.parsed_data.title
        params = {"service": 3, "article": search_title, "count": 1}
        
        try:
            response = self._make_request(
                settings.jstage_base_url, 
                params=params, 
                timeout=settings.jstage_timeout
            )
            if not response: 
                return None, None
                
            soup = BeautifulSoup(response.content, "xml")
            entries = soup.find_all("entry")

            # Note: The fallback search logic using author/year is currently commented out in the original code.
            # If you wish to enable it later, you can uncomment and adjust it here.

            if not entries: 
                return None, None

            best_match = entries[0]

            def get_text_safe(tag_name: str) -> str:
                """
                Helper to safely extract text from J-STAGE XML which often contains
                nested <ja> (Japanese) and <en> (English) tags.
                Prefers Japanese if available, otherwise falls back to English.
                """
                tag = best_match.find(tag_name)
                if not tag: 
                    return ""
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

            raw_bibtex = self._fetch_bibtex_from_doi(doi, timeout=settings.jstage_timeout)
            if not raw_bibtex:
                raw_bibtex = self._generate_fallback_bibtex(metadata, "jstage")

            return metadata, raw_bibtex
        
        except Exception as e:
            print(f"[{self.api_name}] Error during search: {e}")
            return None, None