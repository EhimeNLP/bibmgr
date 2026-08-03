"""Discover official BibTeX exports from DOI landing pages."""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from html import unescape
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests
from lxml import etree, html
from requests.adapters import HTTPAdapter
from requests.packages.urllib3 import HTTPConnectionPool, HTTPSConnectionPool

from ..config import settings
from ..parsing.identifiers import normalize_doi
from .base import APIClientError
from .rate_limit import ProviderRateLimiter


logger = logging.getLogger(__name__)

_AddressResolver = Callable[..., list[tuple]]
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_STREAM_CHUNK_BYTES = 64 * 1024

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


class _PinnedAddressAdapter(HTTPAdapter):
    """Connect to one validated address while preserving HTTP/TLS identity."""

    def __init__(
        self,
        *,
        address: str,
        hostname: str,
        port: int,
        scheme: str,
    ) -> None:
        self._address = address
        self._hostname = hostname
        self._port = port
        self._scheme = scheme
        super().__init__(max_retries=0)

    def get_connection_with_tls_context(
        self,
        request,
        verify,
        proxies=None,
        cert=None,
    ):
        parsed = urlparse(request.url)
        if (
            parsed.scheme != self._scheme
            or parsed.hostname != self._hostname
            or (parsed.port or self._default_port(parsed.scheme)) != self._port
        ):
            raise requests.exceptions.InvalidURL(
                "request URL does not match the pinned origin"
            )
        if self._scheme == "https":
            return HTTPSConnectionPool(
                self._address,
                self._port,
                assert_hostname=self._hostname,
                server_hostname=self._hostname,
                maxsize=1,
                block=True,
            )
        return HTTPConnectionPool(
            self._address,
            self._port,
            maxsize=1,
            block=True,
        )

    @staticmethod
    def _default_port(scheme: str) -> int:
        return 443 if scheme == "https" else 80

    @staticmethod
    def request_url(request, proxies):
        # The pool connects directly to a validated IP, so never emit an
        # absolute proxy-form URL even when proxy variables exist.
        return request.path_url


class OfficialCitationClient:
    """Resolve a DOI and retrieve a BibTeX export advertised by its site."""

    api_name = "Official Citation Site"

    def __init__(
        self,
        session: requests.Session | None = None,
        resolver: _AddressResolver = socket.getaddrinfo,
    ) -> None:
        self._http = session
        self._resolver = resolver
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
            resolved = self._resolve_public_addresses(current_url)
            if not resolved:
                return None
            try:
                response = self._rate_limiter.call(
                    settings.citation_site_wait_sec,
                    lambda: self._request(
                        current_url,
                        address=resolved[0],
                        headers=headers,
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

            if response.status_code not in _REDIRECT_STATUSES:
                break
            location = str(
                (getattr(response, "headers", {}) or {}).get(
                    "Location",
                    "",
                )
            ).strip()
            self._close_response(response)
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
            self._close_response(response)
            return None
        if not 200 <= response.status_code < 400:
            self._close_response(response)
            raise APIClientError(
                api_name=self.api_name,
                operation=operation,
                error_type="HTTPError",
                status_code=response.status_code,
            )
        try:
            buffered = self._buffer_response(response)
        except requests.exceptions.RequestException as exc:
            logger.warning(
                "citation response read failed operation=%s error_type=%s",
                operation,
                exc.__class__.__name__,
            )
            raise APIClientError(
                api_name=self.api_name,
                operation=operation,
                error_type=exc.__class__.__name__,
            ) from exc
        if not buffered:
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

    @classmethod
    def _buffer_response(cls, response: requests.Response) -> bool:
        """Read at most the configured body limit, then close the connection."""

        headers = getattr(response, "headers", {}) or {}
        content_length = headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > settings.citation_site_max_bytes:
                    cls._close_response(response)
                    return False
            except ValueError:
                pass
        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in response.iter_content(
                chunk_size=min(
                    _STREAM_CHUNK_BYTES,
                    settings.citation_site_max_bytes + 1,
                )
            ):
                if not chunk:
                    continue
                total += len(chunk)
                if total > settings.citation_site_max_bytes:
                    return False
                chunks.append(chunk)
            response._content = b"".join(chunks)
            response._content_consumed = True
            return True
        finally:
            cls._close_response(response)

    @staticmethod
    def _close_response(response: requests.Response) -> None:
        response.close()
        session = getattr(response, "_citation_site_session", None)
        if session is not None:
            session.close()

    def _request(
        self,
        url: str,
        *,
        address: str,
        headers: dict[str, str],
    ) -> requests.Response:
        if self._http is not None:
            return self._http.get(
                url,
                headers=headers,
                timeout=settings.citation_site_timeout,
                allow_redirects=False,
                stream=True,
            )
        return self._pinned_get(url, address=address, headers=headers)

    @staticmethod
    def _host_header(hostname: str, port: int, scheme: str) -> str:
        host = f"[{hostname}]" if ":" in hostname else hostname
        default_port = 443 if scheme == "https" else 80
        return host if port == default_port else f"{host}:{port}"

    def _pinned_get(
        self,
        url: str,
        *,
        address: str,
        headers: dict[str, str],
    ) -> requests.Response:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        request_headers = dict(headers)
        request_headers["Host"] = self._host_header(
            hostname,
            port,
            parsed.scheme,
        )
        session = requests.Session()
        session.trust_env = False
        adapter = _PinnedAddressAdapter(
            address=address,
            hostname=hostname,
            port=port,
            scheme=parsed.scheme,
        )
        session.mount(f"{parsed.scheme}://", adapter)
        try:
            response = session.get(
                url,
                headers=request_headers,
                timeout=settings.citation_site_timeout,
                allow_redirects=False,
                stream=True,
            )
        except Exception:
            session.close()
            raise
        response._citation_site_session = session
        return response

    def _is_safe_public_url(self, url: str) -> bool:
        return bool(self._resolve_public_addresses(url))

    def _resolve_public_addresses(self, url: str) -> tuple[str, ...]:
        try:
            parsed = urlparse(url)
        except ValueError:
            return ()
        if parsed.scheme not in {"http", "https"}:
            return ()
        if not parsed.hostname or parsed.username or parsed.password:
            return ()
        try:
            port = parsed.port
        except ValueError:
            return ()
        if port not in {None, 80, 443}:
            return ()
        hostname = parsed.hostname.casefold().rstrip(".")
        if hostname == "localhost" or hostname.endswith(".localhost"):
            return ()
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            try:
                records = self._resolver(
                    hostname,
                    port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            except (OSError, UnicodeError):
                return ()
            addresses = tuple(
                dict.fromkeys(
                    str(record[4][0]).split("%", 1)[0]
                    for record in records
                    if len(record) >= 5 and record[4]
                )
            )
        else:
            addresses = (str(address),)
        if not addresses:
            return ()
        try:
            parsed_addresses = tuple(
                ipaddress.ip_address(value) for value in addresses
            )
        except ValueError:
            return ()
        if not all(address.is_global for address in parsed_addresses):
            return ()
        return tuple(str(address) for address in parsed_addresses)
