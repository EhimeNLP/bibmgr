"""DOI content-negotiation client."""

from __future__ import annotations

import requests

from core.config import settings
from core.identifiers import normalize_doi


class DoiContentNegotiationClient:
    api_name = "DOI Content Negotiation"

    def __init__(self, session: requests.Session | None = None) -> None:
        self._http = session or requests

    def fetch_bibtex(self, doi: str) -> str | None:
        """Fetch the registration agency's BibTeX representation for a DOI."""

        normalized = normalize_doi(doi)
        if not normalized:
            return None

        response = self._http.get(
            f"{settings.doi_base_url.rstrip('/')}/{normalized}",
            headers={
                "Accept": "application/x-bibtex",
                "User-Agent": "bibmgr-bibtex-reconstruction/1.0",
            },
            timeout=settings.doi_timeout,
            allow_redirects=True,
        )
        if response.status_code in {204, 404, 406}:
            return None
        response.raise_for_status()

        source = response.text.strip()
        return source if source.startswith("@") else None
