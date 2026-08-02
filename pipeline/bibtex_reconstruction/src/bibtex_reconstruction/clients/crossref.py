"""Crossref work search client."""

from __future__ import annotations

from typing import Any

from ..config import settings
from ..domain import InputData, VerifiedCitationInfo
from .base import BaseAPIClient


class CrossrefClient(BaseAPIClient):
    """Retrieve DOI metadata including Crossref's structured work type."""

    @property
    def api_name(self) -> str:
        return "Crossref API"

    @property
    def api_prefix(self) -> str:
        return "crossref"

    def _execute_search(self, input_data: InputData):
        params: dict[str, object] = {
            "query.title": input_data.parsed_data.title,
            "rows": 1,
        }
        if settings.crossref_mailto:
            params["mailto"] = settings.crossref_mailto
        response = self._make_request(
            params=params,
            operation="metadata_search",
        )
        if response is None:
            return None, None

        items = response.json().get("message", {}).get("items", [])
        if not isinstance(items, list) or not items:
            return None, None
        best_match = items[0]
        if not isinstance(best_match, dict) or not best_match.get("DOI"):
            return None, None
        raw_authors = best_match.get("author") or []
        if not isinstance(raw_authors, list):
            raw_authors = []

        metadata = VerifiedCitationInfo(
            title=self._first(best_match.get("title")) or "",
            authors=[
                name
                for author in raw_authors
                if isinstance(author, dict)
                and (
                    name := " ".join(
                        filter(
                            None,
                            (
                                str(author.get("given") or "").strip(),
                                str(author.get("family") or "").strip(),
                            ),
                        )
                    )
                )
            ],
            publication_types=[str(best_match.get("type"))]
            if best_match.get("type")
            else [],
            publication_date=self._date(best_match.get("issued")),
            year=self._year(best_match.get("issued")),
            venue=self._first(best_match.get("container-title")) or "",
            publisher=self._text(best_match.get("publisher")),
            volume=self._text(best_match.get("volume")),
            number=self._text(best_match.get("issue")),
            pages=self._text(best_match.get("page")),
            doi=self._text(best_match.get("DOI")),
            url=self._text(best_match.get("URL")),
            raw_payload=best_match,
        )
        return metadata, None

    @staticmethod
    def _first(value: object) -> str | None:
        if not isinstance(value, list) or not value:
            return None
        return CrossrefClient._text(value[0])

    @staticmethod
    def _date(value: object) -> str | None:
        parts = CrossrefClient._date_parts(value)
        return "-".join(str(part) for part in parts) if parts else None

    @staticmethod
    def _year(value: object) -> int | None:
        parts = CrossrefClient._date_parts(value)
        return int(parts[0]) if parts and str(parts[0]).isdigit() else None

    @staticmethod
    def _date_parts(value: object) -> list[Any]:
        if not isinstance(value, dict):
            return []
        date_parts = value.get("date-parts")
        if not isinstance(date_parts, list) or not date_parts:
            return []
        return date_parts[0] if isinstance(date_parts[0], list) else []

    @staticmethod
    def _text(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
