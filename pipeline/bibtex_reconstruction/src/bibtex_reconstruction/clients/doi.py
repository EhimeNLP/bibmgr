"""DOI content-negotiation client."""

from __future__ import annotations

import logging
import socket
from typing import Callable

import requests

from ..config import settings
from ..parsing.identifiers import normalize_doi
from .base import APIClientError
from .citation_site import OfficialCitationClient
from .rate_limit import ProviderRateLimiter


logger = logging.getLogger(__name__)

_AddressResolver = Callable[..., list[tuple]]


class DoiContentNegotiationClient:
    api_name = "DOI Content Negotiation"

    def __init__(
        self,
        session: requests.Session | None = None,
        resolver: _AddressResolver = socket.getaddrinfo,
    ) -> None:
        self._rate_limiter = ProviderRateLimiter.for_provider("doi")
        self._public_http = OfficialCitationClient(
            session=session,
            resolver=resolver,
        )

    def fetch_bibtex(self, doi: str) -> str | None:
        """Fetch the registration agency's BibTeX representation for a DOI."""

        normalized = normalize_doi(doi)
        if not normalized:
            return None

        try:
            response = self._public_http.get_public_response(
                f"{settings.doi_base_url.rstrip('/')}/{normalized}",
                headers={
                    "Accept": "application/x-bibtex",
                    "User-Agent": "bibmgr-bibtex-reconstruction/1.0",
                },
                operation="doi_content_negotiation",
                timeout=settings.doi_timeout,
                wait_sec=settings.doi_wait_sec,
                max_bytes=settings.doi_max_bytes,
                max_redirects=settings.doi_max_redirects,
                rate_limiter=self._rate_limiter,
                api_name=self.api_name,
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

        if response is None:
            return None

        source = response.text.strip()
        return source if source.startswith("@") else None
