"""CiNii Research client with multilingual title and author matching."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..config import settings
from ..domain import InputData, VerifiedCitationInfo
from ..matching import calculate_author_similarity, calculate_citation_similarity
from ..parsing.bibtex import extract_bibtex_field
from .base import BaseAPIClient


class CiNiiClient(BaseAPIClient):
    """Search multiple CiNii records and inspect their multilingual details."""

    @property
    def api_name(self) -> str:
        return "CiNii API"

    @property
    def api_prefix(self) -> str:
        return "cinii"

    @property
    def authoritative_bibtex(self) -> bool:
        return True

    def _execute_search(self, input_data: InputData):
        endpoint_url = f"{self.base_url.rstrip('/')}/articles"
        params: dict[str, object] = {
            # General search includes translated/alternative titles, while the
            # title-only parameter can miss records whose primary title is in
            # another language.
            "q": input_data.parsed_data.title,
            "format": "json",
            "count": settings.cinii_result_count,
            "sortorder": 4,
        }
        if settings.cinii_appid:
            params["appid"] = settings.cinii_appid

        response = self._make_request(
            url=endpoint_url,
            params=params,
            operation="metadata_search",
        )
        if response is None:
            return None, None
        items = response.json().get("items", [])
        if not isinstance(items, list) or not items:
            return None, None

        reference = input_data.parsed_data
        basic = [self._metadata(item, None, reference.authors) for item in items]
        basic = [item for item in basic if item is not None]
        if not basic:
            return None, None

        ranked_basic = sorted(
            basic,
            key=lambda item: self._score(reference, item),
            reverse=True,
        )
        initial_best = ranked_basic[0]
        if self._score(reference, initial_best) >= 0.90:
            detail_targets = [initial_best]
        else:
            detail_targets = ranked_basic[
                : settings.cinii_detail_candidate_count
            ]

        enriched: list[VerifiedCitationInfo] = []
        for metadata in detail_targets:
            detail = self._fetch_detail(metadata.url)
            search_payload = metadata.raw_payload
            item = (
                search_payload.get("search_result", {})
                if isinstance(search_payload, dict)
                else {}
            )
            enriched.append(
                self._metadata(item, detail, reference.authors) or metadata
            )

        candidates = enriched + [
            metadata
            for metadata in ranked_basic
            if metadata not in detail_targets
        ]
        selected = max(
            candidates,
            key=lambda item: self._score(reference, item),
        )

        custom_bibtex = None
        if selected.url:
            bib_resp = self._make_request(
                url=f"{selected.url}.bib",
                operation="citation_export",
                required=False,
            )
            if bib_resp is not None:
                custom_bibtex = bib_resp.text
                extracted_doi = extract_bibtex_field(custom_bibtex, "doi")
                if extracted_doi:
                    selected.doi = extracted_doi
        return selected, custom_bibtex

    def _fetch_detail(self, record_url: str | None) -> dict[str, Any] | None:
        if not record_url:
            return None
        response = self._make_request(
            url=f"{record_url}.json",
            operation="metadata_detail",
            required=False,
        )
        if response is None:
            return None
        payload = response.json()
        return payload if isinstance(payload, dict) else None

    def _metadata(
        self,
        item: dict[str, Any],
        detail: dict[str, Any] | None,
        original_authors: Sequence[str],
    ) -> VerifiedCitationInfo | None:
        if not isinstance(item, dict):
            return None
        primary_title = self._text(item.get("title"))
        detail_titles = self._localized_values(
            (detail or {}).get("dc:title")
        )
        if not primary_title and detail_titles:
            primary_title = detail_titles[0]
        if not primary_title:
            return None
        alternative_titles = self._unique(
            title for title in detail_titles if title != primary_title
        )

        search_authors = self._string_list(item.get("dc:creator"))
        author_groups = self._detail_author_groups(detail)
        if search_authors:
            author_groups.append(search_authors)
        author_groups = self._unique_groups(author_groups)
        authors = max(
            author_groups or [[]],
            key=lambda group: calculate_author_similarity(
                original_authors,
                group,
            ),
        )
        alternative_authors = [
            group for group in author_groups if group != authors
        ]

        publication = (detail or {}).get("publication", {})
        if not isinstance(publication, dict):
            publication = {}
        venue_values = self._localized_values(
            publication.get("prism:publicationName")
        )
        venue = (
            venue_values[0]
            if venue_values
            else self._text(item.get("prism:publicationName"))
        )
        publication_date = (
            publication.get("prism:publicationDate")
            or item.get("prism:publicationDate")
            or ""
        )
        url = self._record_url(item)
        return VerifiedCitationInfo(
            title=primary_title,
            alternative_titles=alternative_titles,
            authors=authors,
            alternative_authors=alternative_authors,
            year=self._extract_year(str(publication_date)),
            venue=venue,
            doi=self._extract_doi(item, detail),
            url=url,
            raw_payload={
                "search_result": item,
                "detail": detail,
            },
        )

    @staticmethod
    def _score(reference, metadata: VerifiedCitationInfo) -> float:
        titles = [metadata.title, *metadata.alternative_titles]
        author_groups = [metadata.authors, *metadata.alternative_authors]
        return max(
            calculate_citation_similarity(
                reference.title or "",
                title,
                original_authors=reference.authors,
                found_authors=authors,
            )
            for title in titles
            for authors in author_groups
        )

    @classmethod
    def _detail_author_groups(
        cls,
        detail: dict[str, Any] | None,
    ) -> list[list[str]]:
        creators = (detail or {}).get("creator", [])
        if not isinstance(creators, list):
            return []
        by_language: dict[str, list[str]] = {}
        for creator in creators:
            if not isinstance(creator, dict):
                continue
            names = creator.get("foaf:name", [])
            if not isinstance(names, list):
                names = [names]
            available: dict[str, str] = {}
            for name in names:
                if not isinstance(name, dict):
                    continue
                value = cls._text(name.get("@value"))
                if value:
                    available[str(name.get("@language", "und"))] = value
            for language, value in available.items():
                by_language.setdefault(language, []).append(value)
        return [group for group in by_language.values() if group]

    @classmethod
    def _extract_doi(
        cls,
        item: dict[str, Any],
        detail: dict[str, Any] | None,
    ) -> str | None:
        for identifier in item.get("dc:identifier", []):
            if (
                isinstance(identifier, dict)
                and identifier.get("@type") == "cir:DOI"
            ):
                return cls._text(identifier.get("@value")) or None
        for product in (detail or {}).get("productIdentifier", []):
            identifier = (
                product.get("identifier", {})
                if isinstance(product, dict)
                else {}
            )
            if identifier.get("@type") == "DOI":
                return cls._text(identifier.get("@value")) or None
        return None

    @classmethod
    def _localized_values(cls, value: object) -> list[str]:
        values = value if isinstance(value, list) else [value]
        return cls._unique(
            cls._text(item.get("@value"))
            for item in values
            if isinstance(item, dict) and cls._text(item.get("@value"))
        )

    @classmethod
    def _string_list(cls, value: object) -> list[str]:
        values = value if isinstance(value, list) else [value]
        return [text for item in values if (text := cls._text(item))]

    @staticmethod
    def _record_url(item: dict[str, Any]) -> str | None:
        link = item.get("link", {})
        if isinstance(link, dict) and link.get("@id"):
            return str(link["@id"])
        identifier = item.get("@id")
        return str(identifier) if identifier else None

    @staticmethod
    def _text(value: object) -> str:
        return str(value).strip() if value is not None else ""

    @staticmethod
    def _unique(values) -> list[str]:
        result: list[str] = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return result

    @staticmethod
    def _unique_groups(values: Sequence[Sequence[str]]) -> list[list[str]]:
        result: list[list[str]] = []
        for value in values:
            group = list(value)
            if group and group not in result:
                result.append(group)
        return result
