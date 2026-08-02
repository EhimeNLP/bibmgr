"""Discover official BibTeX exports from DOI landing pages."""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from html import unescape
from urllib.parse import urljoin, urlparse

import requests
from lxml import etree, html

from ..config import settings
from ..parsing.identifiers import normalize_doi
from .base import APIClientError
from .rate_limit import ProviderRateLimiter


logger = logging.getLogger(__name__)

_BIBTEX_MEDIA_TYPES = {
    "application/x-bibtex",
    "application/bibtex",
    "text/x-bibtex",
}


@dataclass(frozen=True)
class OfficialCitation:
    """BibTeX found on a publisher or repository landing page."""

    bibtex: str
    source_url: str


class OfficialCitationClient:
    """Resolve a DOI and retrieve a BibTeX export advertised by its site."""

    api_name = "Official Citation Site"

    def __init__(self, session: requests.Session | None = None) -> None:
        self._http = session or requests
        self._rate_limiter = ProviderRateLimiter.for_provider("citation_site")

    def fetch_bibtex(self, doi: str) -> OfficialCitation | None:
        """Return an official site BibTeX export when one can be discovered."""

        normalized = normalize_doi(doi)
        if not normalized:
            return None

        landing = self._get(
            f"{settings.doi_base_url.rstrip('/')}/{normalized}",
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "bibmgr-bibtex-reconstruction/1.0",
            },
            operation="landing_page",
        )
        if landing is None:
            return None

        landing_url = str(getattr(landing, "url", "") or "")
        if not self._is_safe_public_url(landing_url):
            logger.warning(
                "citation landing page rejected reason=unsafe_url"
            )
            return None

        content_type = self._content_type(landing)
        source = landing.text.strip()
        if self._looks_like_bibtex(source, content_type):
            return OfficialCitation(source, landing_url)
        if "html" not in content_type and "xhtml" not in content_type:
            return None

        embedded = self._embedded_bibtex(source)
        if embedded:
            return OfficialCitation(embedded, landing_url)

        for citation_url in self._citation_links(source, landing_url):
            response = self._get(
                citation_url,
                headers={
                    "Accept": (
                        "application/x-bibtex,text/x-bibtex,"
                        "text/plain;q=0.9,*/*;q=0.1"
                    ),
                    "User-Agent": "bibmgr-bibtex-reconstruction/1.0",
                },
                operation="citation_export",
            )
            if response is None:
                continue
            candidate = response.text.strip()
            if self._looks_like_bibtex(
                candidate,
                self._content_type(response),
            ):
                return OfficialCitation(
                    candidate,
                    str(getattr(response, "url", "") or citation_url),
                )
        return None

    def _get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        operation: str,
    ) -> requests.Response | None:
        current_url = url
        response: requests.Response | None = None
        for redirect_count in range(
            settings.citation_site_max_redirects + 1
        ):
            if not self._is_safe_public_url(current_url):
                return None
            try:
                response = self._rate_limiter.call(
                    settings.citation_site_wait_sec,
                    lambda: self._http.get(
                        current_url,
                        headers=headers,
                        timeout=settings.citation_site_timeout,
                        allow_redirects=False,
                    ),
                )
            except requests.exceptions.RequestException as exc:
                logger.warning(
                    "citation request failed operation=%s error_type=%s",
                    operation,
                    exc.__class__.__name__,
                )
                raise APIClientError(
                    api_name=self.api_name,
                    operation=operation,
                    error_type=exc.__class__.__name__,
                ) from exc

            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            location = str(
                (getattr(response, "headers", {}) or {}).get(
                    "Location",
                    "",
                )
            ).strip()
            if not location:
                return None
            if redirect_count >= settings.citation_site_max_redirects:
                logger.warning(
                    "citation request failed operation=%s reason=too_many_redirects",
                    operation,
                )
                return None
            current_url = urljoin(current_url, location)

        if response is None:
            return None

        if response.status_code in {204, 404, 406}:
            return None
        if not 200 <= response.status_code < 400:
            raise APIClientError(
                api_name=self.api_name,
                operation=operation,
                error_type="HTTPError",
                status_code=response.status_code,
            )
        if not self._response_size_allowed(response):
            logger.warning(
                "citation response rejected operation=%s reason=too_large",
                operation,
            )
            return None
        final_url = str(getattr(response, "url", "") or current_url)
        if not self._is_safe_public_url(final_url):
            return None
        return response

    @staticmethod
    def _content_type(response: requests.Response) -> str:
        headers = getattr(response, "headers", {}) or {}
        return str(headers.get("Content-Type", "")).split(";", 1)[0].lower()

    @staticmethod
    def _looks_like_bibtex(source: str, content_type: str) -> bool:
        return source.lstrip().startswith("@") and (
            not content_type
            or content_type in _BIBTEX_MEDIA_TYPES
            or content_type.startswith("text/")
            or content_type == "application/octet-stream"
        )

    @staticmethod
    def _embedded_bibtex(source: str) -> str | None:
        try:
            document = html.fromstring(source)
        except (ValueError, etree.ParserError):
            return None

        for element in document.xpath("//pre|//code|//textarea"):
            value = unescape(element.text_content()).strip()
            if value.startswith("@"):
                return value
        for element in document.xpath(
            "//meta[translate(@name, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
            "'abcdefghijklmnopqrstuvwxyz')='citation_bibtex']/@content"
        ):
            value = unescape(str(element)).strip()
            if value.startswith("@"):
                return value
        return None

    def _citation_links(
        self,
        source: str,
        landing_url: str,
    ) -> list[str]:
        try:
            document = html.fromstring(source)
        except (ValueError, etree.ParserError):
            return []

        weighted: list[tuple[int, str]] = []
        for element in document.xpath("//link[@href] | //a[@href]"):
            href = str(element.get("href", "")).strip()
            if not href:
                continue
            media_type = str(element.get("type", "")).lower()
            rel = {
                value.lower()
                for value in str(element.get("rel", "")).split()
            }
            text = " ".join(element.text_content().split()).casefold()
            absolute = urljoin(landing_url, href)
            if not self._is_safe_public_url(absolute):
                continue

            parsed = urlparse(absolute)
            target = f"{parsed.path}?{parsed.query}".casefold()
            score = 0
            if media_type in _BIBTEX_MEDIA_TYPES:
                score += 100
            if "alternate" in rel and "bibtex" in media_type:
                score += 50
            if parsed.path.casefold().endswith(".bib"):
                score += 40
            if "bibtex" in target or "format=bib" in target:
                score += 30
            if "bibtex" in text:
                score += 20
            if element.get("download") is not None and "bib" in target:
                score += 10
            if score:
                weighted.append((score, absolute))

        result: list[str] = []
        for _, url in sorted(weighted, reverse=True):
            if url not in result:
                result.append(url)
            if len(result) >= settings.citation_site_max_links:
                break
        return result

    @staticmethod
    def _response_size_allowed(response: requests.Response) -> bool:
        headers = getattr(response, "headers", {}) or {}
        content_length = headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > settings.citation_site_max_bytes:
                    return False
            except ValueError:
                pass
        return len(response.content) <= settings.citation_site_max_bytes

    @staticmethod
    def _is_safe_public_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        if parsed.scheme not in {"http", "https"}:
            return False
        if not parsed.hostname or parsed.username or parsed.password:
            return False
        try:
            port = parsed.port
        except ValueError:
            return False
        if port not in {None, 80, 443}:
            return False
        hostname = parsed.hostname.casefold().rstrip(".")
        if hostname == "localhost" or hostname.endswith(".localhost"):
            return False
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return True
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )
