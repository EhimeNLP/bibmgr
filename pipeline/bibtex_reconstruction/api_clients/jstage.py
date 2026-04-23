from typing import Optional, Tuple
from bs4 import BeautifulSoup
from models.input_models import InputData
from models.output_models import Metadata
from api_clients.base_client import BaseAPIClient
from core.config import settings

class JStageClient(BaseAPIClient):
    @property
    def api_name(self) -> str:
        return "J-STAGE API"

    def search(self, input_data: InputData) -> Tuple[Optional[Metadata], Optional[str]]:
        if not input_data.parsed_data or not input_data.parsed_data.title:
            return None, None
            
        title = input_data.parsed_data.title
        # author = input_data.parsed_data.authors[0] if input_data.parsed_data.authors else None
        # year = str(input_data.parsed_data.year) if input_data.parsed_data.year else None

        params = {"service": 3, "article": title, "count": 1}
        try:
            response = self._make_request(settings.jstage_base_url, params=params, timeout=settings.jstage_timeout)
            if not response: return None, None
                
            soup = BeautifulSoup(response.content, "xml")
            entries = soup.find_all("entry")

            # if not entries and author and year:
            #     fallback_params = {"service": 3, "author": author, "pubyearfrom": year, "pubyearto": year, "count": 5}
            #     fb_resp = self._make_request(settings.jstage_base_url, params=fallback_params, timeout=settings.jstage_timeout)
            #     if fb_resp:
            #         entries = BeautifulSoup(fb_resp.content, "xml").find_all("entry")

            if not entries: return None, None

            best_match = entries[0]

            def get_text_safe(tag_name):
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
            metadata = Metadata(title=title, authors=authors, year=year, venue=venue, doi=doi, url=url)

            raw_bibtex = self._fetch_bibtex_from_doi(doi, timeout=settings.jstage_timeout)
            if not raw_bibtex:
                raw_bibtex = self._generate_fallback_bibtex(metadata, "jstage")

            return metadata, raw_bibtex
        
        except Exception as e:
            print(f"[{self.api_name}] Error during search: {e}")
            return None, None