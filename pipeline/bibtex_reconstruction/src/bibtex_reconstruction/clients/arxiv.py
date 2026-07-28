import re
from typing import Optional, Tuple
from urllib.parse import quote, urlparse

from ..config import settings
from ..domain import InputData, VerifiedCitationInfo
from ..parsing.xml import element_text, parse_xml
from .base import BaseAPIClient

ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
ARXIV_NAMESPACE = "http://arxiv.org/schemas/atom"
NAMESPACES = {
    "atom": ATOM_NAMESPACE,
    "arxiv": ARXIV_NAMESPACE,
}


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

        response = self._make_request(
            params=params,
            operation="metadata_search",
        )
        if not response:
            return None, None

        root = parse_xml(response.content)
        entry = root.find("atom:entry", namespaces=NAMESPACES)
        if entry is None:
            return None, None

        title = " ".join(
            element_text(
                entry.find("atom:title", namespaces=NAMESPACES)
            ).split()
        )

        authors = [
            name
            for name in (
                element_text(element)
                for element in entry.findall(
                    "atom:author/atom:name",
                    namespaces=NAMESPACES,
                )
            )
            if name
        ]

        published = element_text(
            entry.find("atom:published", namespaces=NAMESPACES)
        )
        year = self._extract_year(published)

        venue = (
            element_text(
                entry.find("arxiv:journal_ref", namespaces=NAMESPACES)
            )
            or "arXiv"
        )

        doi = (
            element_text(entry.find("arxiv:doi", namespaces=NAMESPACES))
            or None
        )
        url = element_text(entry.find("atom:id", namespaces=NAMESPACES))
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
            operation="citation_export",
            required=False,
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
