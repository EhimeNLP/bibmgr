import re
from typing import Optional, Tuple
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup

from api_clients.base_client import BaseAPIClient
from core.config import settings
from models import InputData, VerifiedCitationInfo


class ArxivClient(BaseAPIClient):
    """Client for searching papers and retrieving citations from arXiv."""

    @property
    def api_name(self) -> str:
        return "arXiv API"

    @property
    def api_prefix(self) -> str:
        return "arxiv"

    @property
    def allows_generated_bibtex_fallback(self) -> bool:
        """Never replace an authoritative arXiv citation with guessed BibTeX."""
        return False

    def _execute_search(
        self,
        input_data: InputData,
    ) -> Tuple[Optional[VerifiedCitationInfo], Optional[str]]:
        search_query = f'ti:"{input_data.parsed_data.title}"'
        params = {"search_query": search_query, "start": 0, "max_results": 1}

        response = self._make_request(params=params)
        if not response:
            return None, None

        soup = BeautifulSoup(response.content, "xml")
        entry = soup.find("entry")
        if not entry:
            return None, None

        title_tag = entry.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""
        title = " ".join(title.split())

        authors = [
            author.find("name").get_text(strip=True)
            for author in entry.find_all("author")
            if author.find("name")
        ]

        published_tag = entry.find("published")
        published = published_tag.get_text(strip=True) if published_tag else ""
        year = self._extract_year(published)

        journal_ref = entry.find("arxiv:journal_ref")
        venue = journal_ref.get_text(strip=True) if journal_ref else "arXiv"

        doi_tag = entry.find("arxiv:doi")
        doi = doi_tag.get_text(strip=True) if doi_tag else None
        id_tag = entry.find("id")
        url = id_tag.get_text(strip=True) if id_tag else ""
        arxiv_id = self._extract_arxiv_id(url)

        metadata = VerifiedCitationInfo(
            title=title,
            authors=authors,
            year=year,
            venue=venue,
            doi=doi,
            url=url,
        )

        # A DOI identifies the published work, so BaseAPIClient deliberately
        # prefers DOI content negotiation in that case. For an arXiv-only
        # preprint, use arXiv's own exported citation instead of constructing
        # an @article entry from metadata.
        bibtex = None if doi else self._fetch_official_bibtex(arxiv_id)
        return metadata, bibtex

    def _fetch_official_bibtex(self, arxiv_id: str | None) -> str | None:
        if not arxiv_id:
            return None
        base_url = settings.arxiv_bibtex_base_url.rstrip("/")
        url = f"{base_url}/{quote(arxiv_id, safe='/')}"
        response = self._make_request(
            url=url,
            headers={"Accept": "application/x-bibtex"},
            timeout=self.timeout,
            max_retries=1,
        )
        if not response or response.status_code != 200:
            return None
        source = response.text.strip()
        return source if source.casefold().startswith("@misc") else None

    @staticmethod
    def _extract_arxiv_id(url: str) -> str | None:
        path = urlparse(url).path
        marker = "/abs/"
        if marker not in path:
            return None
        identifier = path.split(marker, 1)[1].strip("/")
        if not identifier:
            return None
        return re.sub(r"v\d+$", "", identifier)
