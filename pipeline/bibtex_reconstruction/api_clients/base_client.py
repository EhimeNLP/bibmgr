import re
import time
import requests
from abc import ABC, abstractmethod
from typing import Optional, Tuple

from models import InputData, VerifiedCitationInfo
from core import settings

class BaseAPIClient(ABC):
    """
    Abstract Base Class for all academic API clients.
    Provides common utilities like request retrying, year extraction, and fallback BibTeX generation.
    """
    
    @property
    @abstractmethod
    def api_name(self) -> str:
        """
        Returns:
            str: The official name of the API (e.g., "Crossref API", "CiNii API").
        """
        pass

    @abstractmethod
    def search(self, input_data: InputData) -> Tuple[Optional[VerifiedCitationInfo], Optional[str]]:
        """
        Executes the search against the specific API.
        
        Args:
            input_data (InputData): The envelope containing the raw parsed data (input_data.parsed_data).
            
        Returns:
            Tuple[Optional[VerifiedCitationInfo], Optional[str]]: 
            A tuple containing the verified metadata (or None if not found) and the BibTeX string (or None).
        """
        pass

    def _make_request(self, url: str, params: dict = None, headers: dict = None, timeout: int = 10, max_retries: int = 3) -> Optional[requests.Response]:
        """
        Helper method to make HTTP requests with exponential backoff for handling rate limits and transient errors.
        
        Args:
            url (str): The target endpoint.
            params (dict, optional): Query parameters.
            headers (dict, optional): HTTP headers.
            timeout (int, optional): Timeout in seconds. Default is 10.
            max_retries (int, optional): Maximum retry attempts. Default is 3.
            
        Returns:
            Optional[requests.Response]: The successful response object, or None if all attempts fail.
        """
        for attempt in range(max_retries):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=timeout)
                
                # Handle specific HTTP 429 Too Many Requests (Rate Limiting)
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        sleep_time = 2 ** attempt
                        print(f"[{self.api_name}] Rate limit exceeded. Retrying in {sleep_time}s... (Attempt {attempt+1}/{max_retries})")
                        time.sleep(sleep_time)
                        continue
                    else:
                        print(f"[{self.api_name}] Rate limit exceeded. Max retries reached for URL: {url}")
                        return None
                    
                response.raise_for_status()
                return response
                
            except requests.exceptions.RequestException as e:
                print(f"[{self.api_name}] Network error during request to {url}: {e}")
                if attempt == max_retries - 1:
                    return None
        return None

    def _extract_year(self, date_str: str) -> Optional[int]:
        """
        Extracts a 4-digit year from various date string formats using regex.
        
        Args:
            date_str (str): Input string (e.g., "2020-05-15", "May 2020").
            
        Returns:
            Optional[int]: The extracted year, or None if no valid year pattern is found.
        """
        if not date_str:
            return None
        match = re.search(r'(\d{4})', str(date_str))
        return int(match.group(1)) if match else None

    def _fetch_bibtex_from_doi(self, doi: str, timeout: int = 10) -> Optional[str]:
        """
        Fetches official BibTeX data directly from a DOI registry via content negotiation.
        
        Args:
            doi (str): The DOI string (e.g., "10.1038/s41586-020-2649-2").
            timeout (int, optional): Request timeout in seconds.
            
        Returns:
            Optional[str]: The official BibTeX string, or None if the request fails.
        """
        if not doi:
            return None
            
        # Clean up DOI string just in case it contains URL prefixes
        clean_doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
        url = f"{settings.doi_base_url}{clean_doi}"
        headers = {"Accept": "application/x-bibtex"}
        
        response = self._make_request(url, headers=headers, timeout=timeout, max_retries=1)
        if response and response.status_code == 200:
            return response.text
        return None

    def _generate_fallback_bibtex(self, metadata: VerifiedCitationInfo, api_prefix: str) -> str:
        """
        Generates a basic, structural BibTeX entry based on available metadata 
        when official DOI-based retrieval is impossible.
        
        Args:
            metadata (VerifiedCitationInfo): The verified metadata gathered by the API client.
            api_prefix (str): A short string (e.g., 'cinii', 'arxiv') used to generate a unique BibTeX key.
            
        Returns:
            str: The constructed BibTeX string.
        """ 
        bib_type = "article"
        venue_field = "journal"
        venue = metadata.venue or ""
        
        if venue:
            venue_lower = venue.lower()
            inproceedings_keywords = ["大会", "シンポジウム", "会議", "proceedings", "conference", "symposium", "workshop"]
            
            if any(k in venue_lower for k in inproceedings_keywords):
                bib_type = "inproceedings"
                venue_field = "booktitle"
            elif "arxiv" in venue_lower:
                bib_type = "article"
                venue_field = "journal"
                venue = f"arXiv preprint {venue}"
            elif "thesis" in venue_lower or "学位" in venue_lower:
                bib_type = "phdthesis"
                venue_field = "school"
            elif "book" in venue_lower or "図書" in venue_lower:
                bib_type = "book"
                venue_field = "publisher"

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