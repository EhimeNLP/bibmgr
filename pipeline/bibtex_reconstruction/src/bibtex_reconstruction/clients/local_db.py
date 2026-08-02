"""Read-only lookup against the BibMgR reference library."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests

from ..config import settings
from ..domain import InputData, VerifiedCitationInfo
from ..matching import calculate_similarity
from ..parsing.identifiers import normalize_doi
from .base import APIClientError


logger = logging.getLogger(__name__)


class LocalDBClient:
    """Return an already-validated BibTeX source without rewriting it."""

    api_name = "BibMgR Local DB"

    def search(
        self,
        input_data: InputData,
    ) -> tuple[VerifiedCitationInfo | None, str | None]:
        reference = input_data.parsed_data
        title = (reference.title or "").strip()
        doi = normalize_doi(reference.doi)
        if not title and not doi:
            return None, None
        logger.info(
            "local DB search started ref_id=%s",
            reference.id,
        )
        endpoint = settings.localdb_base_url
        self._validate_endpoint(endpoint)
        headers: dict[str, str] = {}
        if settings.localdb_cookie:
            headers["Cookie"] = settings.localdb_cookie
        params: dict[str, str | int] = {
            "query": title,
            "limit": 25,
            "offset": 0,
        }
        if doi:
            params["identifier"] = doi
        if reference.authors:
            params["author"] = reference.authors[0]
        if reference.comparison_year:
            params["year"] = reference.comparison_year
        try:
            response = requests.get(
                endpoint,
                params=params,
                headers=headers,
                timeout=settings.localdb_timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.RequestException as exc:
            status_code = (
                exc.response.status_code
                if exc.response is not None
                else None
            )
            raise APIClientError(
                api_name=self.api_name,
                operation="reference_search",
                error_type=exc.__class__.__name__,
                status_code=status_code,
            ) from exc
        except (TypeError, ValueError) as exc:
            raise APIClientError(
                api_name=self.api_name,
                operation="reference_search",
                error_type="InvalidResponse",
            ) from exc

        items = payload.get("items", []) if isinstance(payload, dict) else []
        matches = [
            item for item in items
            if isinstance(item, dict) and self._matches(input_data, item)
        ]
        if not matches:
            logger.info(
                "local DB search completed ref_id=%s status=not_found",
                reference.id,
            )
            return None, None
        best = max(
            matches,
            key=lambda item: calculate_similarity(
                title,
                str(item.get("title", "")),
            ) if title else 1.0,
        )
        bibtex = best.get("bibtex")
        if not isinstance(bibtex, str) or not bibtex.strip():
            return None, None
        metadata = VerifiedCitationInfo(
            title=str(best.get("title", "")),
            authors=[
                author
                for author in best.get("authors", [])
                if isinstance(author, str) and author.strip()
            ],
            year=best.get("year") if isinstance(best.get("year"), int) else None,
            venue=best.get("venue") if isinstance(best.get("venue"), str) else None,
            doi=best.get("doi") if isinstance(best.get("doi"), str) else None,
            url=best.get("url") if isinstance(best.get("url"), str) else None,
        )
        logger.info(
            "local DB search completed ref_id=%s status=match",
            reference.id,
        )
        return metadata, bibtex

    @staticmethod
    def _validate_endpoint(endpoint: str) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("local DB URL must use HTTP or HTTPS")
        if parsed.scheme == "http" and parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError(
                "plain HTTP is only allowed for a loopback local DB URL"
            )

    @staticmethod
    def _matches(input_data: InputData, item: dict[str, object]) -> bool:
        reference = input_data.parsed_data
        expected_doi = normalize_doi(reference.doi)
        found_doi = normalize_doi(
            item.get("doi") if isinstance(item.get("doi"), str) else None
        )
        if expected_doi and found_doi:
            return expected_doi == found_doi

        found_title = str(item.get("title", ""))
        if calculate_similarity(reference.title or "", found_title) < (
            settings.similarity_threshold
        ):
            return False
        expected_year = reference.comparison_year
        found_year = item.get("year")
        if (
            expected_year is not None
            and isinstance(found_year, int)
            and expected_year != found_year
        ):
            return False
        expected_authors = _author_tokens(reference.authors)
        found_authors = _author_tokens(
            item.get("authors") if isinstance(item.get("authors"), list) else []
        )
        return (
            not expected_authors
            or not found_authors
            or bool(expected_authors & found_authors)
        )


def _author_tokens(authors: list[object]) -> set[str]:
    return {
        token
        for author in authors
        if isinstance(author, str)
        for token in author.casefold().replace(",", " ").split()
        if len(token) >= 2
    }
