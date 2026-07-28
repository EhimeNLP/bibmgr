import re
import time
import requests
from abc import ABC, abstractmethod
from typing import Optional, Tuple
from urllib.parse import urlparse
from ..config import settings
from ..domain import InputData, VerifiedCitationInfo

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

        if self.wait_sec > 0:
            time.sleep(self.wait_sec)   # 2. Rate Limiting (Throttling)

        try:
            metadata, custom_bibtex = self._execute_search(input_data)  # 3. Delegate specific search logic to subclasses
            
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

        except Exception as e:
            print(f"[{self.api_name}] Error during search pipeline: {e}")
            return None, None

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
            print(f"[{self.api_name}] Validation failed: title is empty.")
            return False

        if metadata.year is not None:
            if not isinstance(metadata.year, int) or not (1000 <= metadata.year <= 2999):
                print(f"[{self.api_name}] Validation failed: year '{metadata.year}' is not a valid 4-digit year.")
                return False

        if any(not isinstance(a, str) or not a.strip() for a in metadata.authors):
            print(f"[{self.api_name}] Validation failed: authors list contains empty or non-string entries.")
            return False

        return True

    def _is_safe_url(self, url: str) -> bool:
        """
        SSRF Mitigation: Validates the URL scheme and host against a strict whitelist.
        """
        try:
            parsed = urlparse(url)
            if parsed.scheme not in self._ALLOWED_SCHEMES:
                print(f"[{self.api_name}] SSRF Blocked: Disallowed scheme '{parsed.scheme}'")
                return False
            
            if parsed.hostname not in self._ALLOWED_HOSTS:
                print(f"[{self.api_name}] SSRF Blocked: Disallowed host '{parsed.hostname}'")
                return False
                
            return True
        except Exception as e:
            print(f"[{self.api_name}] URL parsing error during SSRF validation: {e}")
            return False

    def _make_request(self, url: Optional[str] = None, params: dict = None, headers: dict = None, 
                      timeout: Optional[int] = None, max_retries: Optional[int] = None) -> Optional[requests.Response]:
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
            print(f"[{self.api_name}] Error: Base URL is not defined.")
            return None

        if req_url.startswith("http://"):
            req_url = req_url.replace("http://", "https://", 1)

        if not self._is_safe_url(req_url):
            return None

        for attempt in range(retries):
            try:
                response = requests.get(req_url, params=params, headers=headers, timeout=req_timeout)
                
                if response.status_code == 429:
                    if attempt < retries - 1:
                        sleep_time = settings.retry_backoff_sec ** (attempt + 1)
                        print(f"[{self.api_name}] Rate limit reached. Retrying in {sleep_time}s...")
                        time.sleep(sleep_time)
                        continue
                    return None
                    
                response.raise_for_status()
                return response
                
            except requests.exceptions.RequestException as e:
                print(f"[{self.api_name}] Network error: {e}")
                if attempt == retries - 1:
                    return None
        return None

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
        
        response = self._make_request(url, headers=headers, timeout=timeout, max_retries=1)
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
