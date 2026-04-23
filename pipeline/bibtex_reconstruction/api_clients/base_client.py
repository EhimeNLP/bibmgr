# api_clients/base_client.py
import re
import time
import requests
from abc import ABC, abstractmethod
from typing import Optional, Tuple
from models.input_models import InputData
from models.output_models import Metadata
from core.config import settings

class BaseAPIClient(ABC):
    """Base API Client with common utilities for all API clients"""
    
    @property
    @abstractmethod
    def api_name(self) -> str:
        """
        Return:
            str: The name of the API (e.g., "Crossref API", "CiNii API")
        """
        pass

    @abstractmethod
    def search(self, input_data: InputData) -> Tuple[Optional[Metadata], Optional[str]]:
        """
        Args:
            input_data (InputData): The parsed input data containing title, authors, year, etc.
        Returns:
            Tuple[Optional[Metadata], Optional[str]]: A tuple of (Metadata object or None, BibTeX string or None)
        """
        pass

    def _make_request(self, url: str, params: dict = None, headers: dict = None, timeout: int = 10, max_retries: int = 3) -> Optional[requests.Response]:
        """
        A helper method to make HTTP requests with retry logic for handling transient errors and rate limits.
        Args:
            url (str): The URL to send the request to.
            params (dict, optional): Query parameters for GET requests.
            headers (dict, optional): HTTP headers to include in the request.
            timeout (int, optional): Timeout for the request in seconds. Default is 10 seconds
            max_retries (int, optional): Maximum number of retry attempts for transient errors. Default is 3.
        Returns:
            Optional[requests.Response]: The HTTP response object if the request was successful, or None if all retries failed.    
        """

        for attempt in range(max_retries):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=timeout)
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        sleep_time = 2 ** attempt
                        print(f"Rate limit exceeded. Retrying in {sleep_time} seconds... (Attempt {attempt+1}/{max_retries})")
                        time.sleep(sleep_time)
                        continue
                    else:
                        print(f"Rate limit exceeded. Max retries reached for URL: {url}")
                        return None
                    
                response.raise_for_status()
                return response
            except Exception as e:
                print(f"Error during request to {url}: {e}")
                if attempt == max_retries - 1:
                    return None
        return None

    def _extract_year(self, date_str: str) -> Optional[int]:
        """
        A helper method to extract the year from a date string using regular expressions.
        Args:
            date_str (str): The input date string (e.g., "2020-0515", "May 2020", "2020").
        Returns:
            Optional[int]: The extracted year as an integer, or None if no valid year is found.
        """

        if not date_str:
            return None
        match = re.search(r'(\d{4})', str(date_str))
        return int(match.group(1)) if match else None

    def _fetch_bibtex_from_doi(self, doi: str, timeout: int = 10) -> Optional[str]:
        """
        A helper method to fetch BibTeX data from a DOI using content negotiation.
        Args:
            doi (str): The DOI string to fetch BibTeX for.
            timeout (int, optional): Timeout for the request in seconds. Default is 10 seconds.
        Returns:
            Optional[str]: The BibTeX string if successfully retrieved, or None if the request fails or the DOI is invalid.
        """

        if not doi:
            return None
        url = f"{settings.doi_base_url}{doi}"
        headers = {"Accept": "application/x-bibtex"}
        response = self._make_request(url, headers=headers, timeout=timeout, max_retries=1)
        if response and response.status_code == 200:
            return response.text
        return None

    def _generate_fallback_bibtex(self, metadata: Metadata, api_prefix: str) -> str:
        """
        A helper method to generate a fallback BibTeX entry when DOI-based retrieval fails.
        Args:
            metadata (Metadata): The metadata object containing title, authors, year, venue, etc.
            api_prefix (str): A prefix to use in the BibTeX key to indicate the source API (e.g., "jstage", "cinii").
        Returns:
            str: A generated BibTeX entry as a string.
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