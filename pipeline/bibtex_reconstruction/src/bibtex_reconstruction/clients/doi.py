"""DOI content-negotiation client."""

from __future__ import annotations

import logging

import requests

from ..config import settings
from ..parsing.identifiers import normalize_doi
from .base import APIClientError
from .rate_limit import ProviderRateLimiter


logger = logging.getLogger(__name__)


class DoiContentNegotiationClient:
    api_name = "DOI Content Negotiation"

    def __init__(self, session: requests.Session | None = None) -> None:
        self._http = session or requests
        self._rate_limiter = ProviderRateLimiter.for_provider("doi")

    def fetch_bibtex(self, doi: str) -> str | None:
        """Fetch the registration agency's BibTeX representation for a DOI."""

        normalized = normalize_doi(doi)
        if not normalized:
            return None

        try:
            response = self._rate_limiter.call(
                settings.doi_wait_sec,
                lambda: self._http.get(
                    f"{settings.doi_base_url.rstrip('/')}/{normalized}",
                    headers={
                        "Accept": "application/x-bibtex",
                        "User-Agent": "bibmgr-bibtex-reconstruction/1.0",
                    },
                    timeout=settings.doi_timeout,
                    allow_redirects=True,
                ),
            )
        except requests.exceptions.RequestException as exc:
            logger.warning(
                (
                    "network request failed api=%s operation=%s "
                    "error_type=%s"
                ),
                self.api_name,
                "doi_content_negotiation",
                exc.__class__.__name__,
            )
            raise APIClientError(
                api_name=self.api_name,
                operation="doi_content_negotiation",
                error_type=exc.__class__.__name__,
            ) from exc

        if response.status_code in {204, 404, 406}:
            return None
        if not 200 <= response.status_code < 400:
            logger.warning(
                "HTTP request failed api=%s operation=%s http_status=%d",
                self.api_name,
                "doi_content_negotiation",
                response.status_code,
            )
            raise APIClientError(
                api_name=self.api_name,
                operation="doi_content_negotiation",
                error_type="HTTPError",
                status_code=response.status_code,
            )

        source = response.text.strip()
        return source if source.startswith("@") else None
