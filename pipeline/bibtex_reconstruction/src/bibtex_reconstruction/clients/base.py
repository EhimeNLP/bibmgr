import logging
import re
import requests
from abc import ABC, abstractmethod
from typing import Optional, Tuple
from urllib.parse import urlparse
from ..config import settings
from ..domain import InputData, VerifiedCitationInfo
from .rate_limit import ProviderRateLimiter


logger = logging.getLogger(__name__)


class APIClientError(RuntimeError):
    """A non-sensitive error propagated to the reconstruction audit report."""

    def __init__(
        self,
        *,
        api_name: str,
        operation: str,
        error_type: str,
        status_code: int | None = None,
    ) -> None:
        self.api_name = api_name
        self.operation = operation
        self.error_type = error_type
        self.status_code = status_code
        super().__init__(self.safe_summary)

    @property
    def safe_summary(self) -> str:
        parts = [
            f"error_type={self.error_type}",
            f"operation={self.operation}",
        ]
        if self.status_code is not None:
            parts.append(f"http_status={self.status_code}")
        return " ".join(parts)


class BaseAPIClient(ABC):
    """
    Abstract Base Class for all academic API clients.
    Provides a unified search pipeline and common utilities.
    """

    _ALLOWED_SCHEMES = {"https"}
    _ALLOWED_HOSTS = {
        "doi.org",
        "api.crossref.org",
        "cir.nii.ac.jp",
        "api.semanticscholar.org",
        "api.jstage.jst.go.jp",
        "export.arxiv.org",
        "arxiv.org",
    }

    def __init__(self) -> None:
        self._rate_limiter = ProviderRateLimiter.for_provider(self.api_prefix)
    
    @property
    @abstractmethod
    def api_name(self) -> str:
        """
        Returns the official name of the API.
        
        Returns:
            str: The API name (e.g., 'Crossref API').
        """
        pass

    @property
    @abstractmethod
    def api_prefix(self) -> str:
        """
        Returns the prefix used for fallback BibTeX keys.
        
        Returns:
            str: The unique prefix (e.g., 'crossref', 'semanticscholar').
        """
        pass

    @property
    def wait_sec(self) -> float:
        """Dynamically retrieves the wait time from settings using api_prefix."""
        return getattr(settings, f"{self.api_prefix}_wait_sec", 0.0)

    @property
    def base_url(self) -> str:
        """Dynamically retrieves the base URL from settings using api_prefix."""
        return getattr(settings, f"{self.api_prefix}_base_url", "")

    @property
    def timeout(self) -> int:
        """Dynamically retrieves the timeout from settings using api_prefix."""
        return getattr(settings, f"{self.api_prefix}_timeout", 10)

    @property
    def allows_generated_bibtex_fallback(self) -> bool:
        """Whether metadata may be converted to a locally generated entry."""
        return True

    def search(self, input_data: InputData) -> Tuple[Optional[VerifiedCitationInfo], Optional[str]]:
        """
        Executes the common search pipeline including validation, rate limiting, and BibTeX retrieval.
        Subclasses should implement _execute_search() instead of overriding this method.

        Args:
            input_data (InputData): The envelope containing parsed reference data.

        Returns:
            Tuple[Optional[VerifiedCitationInfo], Optional[str]]: 
            A tuple of (verified metadata, BibTeX string). Both are None if search fails.
        """
        if not input_data.parsed_data or not input_data.parsed_data.title:
            return None, None   # 1. Validation

        ref_id = input_data.parsed_data.id
        logger.debug("API search started api=%s ref_id=%s", self.api_name, ref_id)
        try:
            metadata, custom_bibtex = self._execute_search(input_data)
            
            if not metadata or not metadata.title.strip():
                return None, None

            if not self._validate_metadata(metadata):   # 4. Common metadata validation
                return None, None

            raw_bibtex = custom_bibtex  # 5. Determine BibTeX string
            
            if not raw_bibtex and metadata.doi:
                raw_bibtex = self._fetch_bibtex_from_doi(metadata.doi)  # Fetch from DOI if not provided by the specific API logic
                
            if not raw_bibtex and self.allows_generated_bibtex_fallback:
                raw_bibtex = self._generate_fallback_bibtex(metadata, self.api_prefix)  # Fallback if still missing

            return metadata, raw_bibtex

        except APIClientError:
            raise
        except Exception as exc:
            logger.warning(
                "API search pipeline failed api=%s ref_id=%s error_type=%s",
                self.api_name,
                ref_id,
                exc.__class__.__name__,
            )
            raise APIClientError(
                api_name=self.api_name,
                operation="search_pipeline",
                error_type=exc.__class__.__name__,
            ) from exc

    @abstractmethod
    def _execute_search(self, input_data: InputData) -> Tuple[Optional[VerifiedCitationInfo], Optional[str]]:
        """
        Internal method for API-specific communication and metadata extraction.

        Args:
            input_data (InputData): The search parameters.

        Returns:
            Tuple[Optional[VerifiedCitationInfo], Optional[str]]: 
            A tuple of (extracted metadata, API-specific BibTeX).
        """
        pass

    def _validate_metadata(self, metadata: VerifiedCitationInfo) -> bool:
        """
        Validates that the metadata returned by _execute_search() meets
        the minimum requirements for downstream processing.

        Rules (common to all clients):
            - title   : must be a non-empty string after stripping whitespace.
            - year    : if present, must be a 4-digit integer (1000–2999).
            - authors : empty list is allowed; individual entries must be non-empty strings.
            - url     : no constraint (None is fine).
            - venue   : no constraint (None is fine).

        Subclasses may override this method to add stricter checks
        (e.g. CrossrefClient requiring a DOI).

        Args:
            metadata (VerifiedCitationInfo): Metadata to validate.

        Returns:
            bool: True if metadata passes all checks, False otherwise.
        """
        if not metadata.title or not metadata.title.strip():
            logger.debug(
                "API metadata rejected api=%s reason=empty_title",
                self.api_name,
            )
            return False

        if metadata.year is not None:
            if not isinstance(metadata.year, int) or not (1000 <= metadata.year <= 2999):
                logger.debug(
                    "API metadata rejected api=%s reason=invalid_year",
                    self.api_name,
                )
                return False

        if any(not isinstance(a, str) or not a.strip() for a in metadata.authors):
            logger.debug(
                "API metadata rejected api=%s reason=invalid_authors",
                self.api_name,
            )
            return False

        return True

    def _is_safe_url(self, url: str) -> bool:
        """
        SSRF Mitigation: Validates the URL scheme and host against a strict whitelist.
        """
        try:
            parsed = urlparse(url)
            if parsed.scheme not in self._ALLOWED_SCHEMES:
                logger.warning(
                    "request blocked api=%s reason=disallowed_scheme scheme=%s",
                    self.api_name,
                    parsed.scheme,
                )
                return False
            
            if parsed.hostname not in self._ALLOWED_HOSTS:
                logger.warning(
                    "request blocked api=%s reason=disallowed_host host=%s",
                    self.api_name,
                    parsed.hostname,
                )
                return False
                
            return True
        except Exception as exc:
            logger.warning(
                "request URL validation failed api=%s error_type=%s",
                self.api_name,
                exc.__class__.__name__,
            )
            return False

    def _make_request(
        self,
        url: Optional[str] = None,
        params: dict = None,
        headers: dict = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        *,
        operation: str = "request",
        required: bool = True,
    ) -> Optional[requests.Response]:
        """
        Helper method to make HTTP requests with exponential backoff.

        Args:
            url (str): Target endpoint.
            params (dict, optional): Query parameters.
            headers (dict, optional): HTTP headers.
            timeout (int, optional): Request timeout.
            max_retries (int, optional): Maximum attempts. Defaults to settings.max_retries.

        Returns:
            Optional[requests.Response]: Response object or None if failed.
        """
        req_url = url or self.base_url
        req_timeout = timeout or self.timeout
        retries = max_retries if max_retries is not None else settings.max_retries

        if not req_url:
            logger.error("request failed api=%s reason=missing_base_url", self.api_name)
            if required:
                raise APIClientError(
                    api_name=self.api_name,
                    operation=operation,
                    error_type="MissingBaseUrl",
                )
            return None

        if req_url.startswith("http://"):
            req_url = req_url.replace("http://", "https://", 1)

        if not self._is_safe_url(req_url):
            if required:
                raise APIClientError(
                    api_name=self.api_name,
                    operation=operation,
                    error_type="UnsafeRequestUrl",
                )
            return None

        parsed_url = urlparse(req_url)
        if parsed_url.hostname == "doi.org":
            rate_limiter = ProviderRateLimiter.for_provider("doi")
            minimum_interval = settings.doi_wait_sec
        else:
            rate_limiter = self._rate_limiter
            minimum_interval = self.wait_sec

        for attempt_index in range(retries):
            attempt = attempt_index + 1
            try:
                response = rate_limiter.call(
                    minimum_interval,
                    lambda: requests.get(
                        req_url,
                        params=params,
                        headers=headers,
                        timeout=req_timeout,
                    ),
                    cooldown_after=lambda result: (
                        self._retry_delay(attempt, response=result)
                        if (
                            result.status_code == 429
                            or result.status_code >= 500
                        )
                        and attempt < retries
                        else 0
                    ),
                    error_cooldown=(
                        self._retry_delay(attempt)
                        if attempt < retries
                        else 0
                    ),
                )
            except requests.exceptions.RequestException as exc:
                logger.warning(
                    (
                        "network request failed api=%s operation=%s "
                        "attempt=%d/%d error_type=%s"
                    ),
                    self.api_name,
                    operation,
                    attempt,
                    retries,
                    exc.__class__.__name__,
                )
                if attempt < retries:
                    continue
                error = APIClientError(
                    api_name=self.api_name,
                    operation=operation,
                    error_type=exc.__class__.__name__,
                )
                if required:
                    raise error from exc
                return None

            status_code = response.status_code
            if 200 <= status_code < 400:
                return response

            retryable = status_code == 429 or status_code >= 500
            wait_seconds = self._retry_delay(attempt, response=response)
            if status_code == 429:
                logger.warning(
                    (
                        "rate limited api=%s operation=%s http_status=%d "
                        "attempt=%d/%d retryable=%s wait_seconds=%s"
                    ),
                    self.api_name,
                    operation,
                    status_code,
                    attempt,
                    retries,
                    retryable and attempt < retries,
                    wait_seconds,
                )
            else:
                logger.warning(
                    (
                        "HTTP request failed api=%s operation=%s "
                        "http_status=%d attempt=%d/%d retryable=%s"
                    ),
                    self.api_name,
                    operation,
                    status_code,
                    attempt,
                    retries,
                    retryable and attempt < retries,
                )

            if retryable and attempt < retries:
                continue

            error = APIClientError(
                api_name=self.api_name,
                operation=operation,
                error_type=(
                    "RateLimited" if status_code == 429 else "HTTPError"
                ),
                status_code=status_code,
            )
            if required:
                raise error
            return None
        return None

    @staticmethod
    def _retry_delay(
        attempt: int,
        *,
        response: requests.Response | None = None,
    ) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return max(float(retry_after), 0.0)
                except ValueError:
                    pass
        return float(settings.retry_backoff_sec ** attempt)

    def _extract_year(self, date_str: str) -> Optional[int]:
        """
        Extracts a 4-digit year from a string.

        Args:
            date_str (str): Date-like string.

        Returns:
            Optional[int]: The 4-digit year.
        """
        if not date_str:
            return None
        match = re.search(r'(\d{4})', str(date_str))
        return int(match.group(1)) if match else None

    def _fetch_bibtex_from_doi(self, doi: str, timeout: int = 10) -> Optional[str]:
        """
        Fetches official BibTeX data via content negotiation from DOI.org.

        Args:
            doi (str): DOI string.
            timeout (int, optional): Request timeout.

        Returns:
            Optional[str]: BibTeX string or None.
        """
        if not doi:
            return None
        clean_doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
        url = f"{settings.doi_base_url}{clean_doi}"
        headers = {"Accept": "application/x-bibtex"}
        
        response = self._make_request(
            url,
            headers=headers,
            timeout=timeout,
            max_retries=1,
            operation="doi_content_negotiation",
            required=False,
        )
        if response and response.status_code == 200:
            return response.text
        return None

    def _generate_fallback_bibtex(self, metadata: VerifiedCitationInfo, api_prefix: str) -> str:
        """
        Generates a structural fallback BibTeX entry.

        Args:
            metadata (VerifiedCitationInfo): The metadata used for generation.
            api_prefix (str): Prefix for the BibTeX key.

        Returns:
            str: Constructed BibTeX string.
        """
        bib_type = "article"
        venue_field = "journal"
        venue = (metadata.venue or "").strip().replace('\n', ' ')
        
        if venue:
            venue_lower = venue.lower()
            inproceedings_keywords = ["大会", "シンポジウム", "会議", "proceedings", "conference", "symposium", "workshop"]
            if any(k in venue_lower for k in inproceedings_keywords):
                bib_type = "inproceedings"
                venue_field = "booktitle"

        bib_authors = " and ".join(metadata.authors) if metadata.authors else "Unknown"
        year_val = metadata.year if metadata.year else "unknown"
        temp_key = f"{api_prefix}_{year_val}"
        
        return (
            f"@{bib_type}{{{temp_key},\n"
            f"  title = {{{metadata.title}}},\n"
            f"  author = {{{bib_authors}}},\n"
            f"  {venue_field} = {{{venue}}},\n"
            f"  year = {{{year_val}}},\n"
            f"  url = {{{metadata.url or ''}}}\n"
            f"}}"
        )
