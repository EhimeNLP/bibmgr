"""Semantic Scholar paper search with structured publication evidence."""

from __future__ import annotations

from typing import Any

from ..config import settings
from ..domain import InputData, VerifiedCitationInfo
from .base import BaseAPIClient


class SemanticScholarClient(BaseAPIClient):
    """Retrieve identity, publication type, and provider citation styles."""

    @property
    def api_name(self) -> str:
        return "Semantic Scholar API"

    @property
    def api_prefix(self) -> str:
        return "semanticscholar"

    @property
    def direct_bibtex_eligible(self) -> bool:
        # citationStyles.bibtex is returned by the provider and remains
        # distinguishable from a publisher-authoritative citation.
        return True

    def _execute_search(self, input_data: InputData):
        headers = (
            {"x-api-key": settings.semanticscholar_api_key}
            if settings.semanticscholar_api_key
            else {}
        )
        params = {
            "query": input_data.parsed_data.title,
            "limit": 1,
            "fields": ",".join(
                (
                    "title",
                    "authors",
                    "year",
                    "venue",
                    "publicationTypes",
                    "publicationDate",
                    "journal",
                    "externalIds",
                    "url",
                    "citationStyles",
                )
            ),
        }
        response = self._make_request(
            params=params,
            headers=headers,
            operation="metadata_search",
        )
        if response is None:
            return None, None

        data = response.json().get("data", [])
        if not isinstance(data, list) or not data:
            return None, None
        best_match = data[0]
        if not isinstance(best_match, dict):
            return None, None

        journal = best_match.get("journal") or {}
        if not isinstance(journal, dict):
            journal = {}
        venue = str(
            best_match.get("venue") or journal.get("name") or ""
        ).strip()
        external_ids = best_match.get("externalIds") or {}
        if not isinstance(external_ids, dict):
            external_ids = {}
        metadata = VerifiedCitationInfo(
            title=str(best_match.get("title") or ""),
            authors=self._authors(best_match.get("authors")),
            publication_types=self._strings(
                best_match.get("publicationTypes")
            ),
            publication_date=self._optional_text(
                best_match.get("publicationDate")
            ),
            year=best_match.get("year"),
            venue=venue,
            volume=self._optional_text(journal.get("volume")),
            pages=self._optional_text(journal.get("pages")),
            doi=self._optional_text(external_ids.get("DOI")),
            url=self._optional_text(best_match.get("url")),
            raw_payload=best_match,
        )
        citation_styles = best_match.get("citationStyles") or {}
        bibtex = (
            citation_styles.get("bibtex")
            if isinstance(citation_styles, dict)
            else None
        )
        if not isinstance(bibtex, str) or not bibtex.strip().startswith("@"):
            bibtex = None
        return metadata, bibtex

    @classmethod
    def _authors(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [
            name
            for author in value
            if isinstance(author, dict)
            and (name := cls._optional_text(author.get("name")))
        ]

    @classmethod
    def _strings(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [text for item in value if (text := cls._optional_text(item))]

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
