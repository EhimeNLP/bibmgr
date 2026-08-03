from __future__ import annotations

from typing import Optional, Tuple

from lxml import etree

from ..domain import InputData, VerifiedCitationInfo
from ..matching import calculate_citation_similarity
from ..parsing.xml import element_text, parse_xml
from .base import APIClientError, BaseAPIClient

ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
PRISM_NAMESPACE = "http://prismstandard.org/namespaces/basic/2.0/"
NAMESPACES = {
    "atom": ATOM_NAMESPACE,
    "prism": PRISM_NAMESPACE,
}


class JStageClient(BaseAPIClient):
    """Client for searching academic papers via the J-STAGE Atom API."""

    @property
    def api_name(self) -> str:
        return "J-STAGE API"

    @property
    def api_prefix(self) -> str:
        return "jstage"

    def _execute_search(
        self,
        input_data: InputData,
    ) -> Tuple[Optional[VerifiedCitationInfo], Optional[str]]:
        params = {
            "service": 3,
            "article": input_data.parsed_data.title,
            "count": 1,
        }

        response = self._make_request(
            params=params,
            operation="metadata_search",
        )
        if not response:
            return None, None

        root = parse_xml(response.content)
        status = element_text(
            root.find("atom:result/atom:status", namespaces=NAMESPACES)
        )
        if status and status != "0":
            raise APIClientError(
                api_name=self.api_name,
                operation="metadata_search",
                error_type="ProviderResponseError",
            )

        entry = root.find("atom:entry", namespaces=NAMESPACES)
        if entry is None:
            return None, None

        titles = self._localized_texts(entry, "article_title")
        author_groups = self._localized_authors(entry)
        primary_language = self._primary_language(
            input_data,
            titles,
            author_groups,
        )
        if primary_language is None:
            return None, None
        title = titles[primary_language]
        alternative_titles = self._alternatives(
            titles,
            primary_language,
        )
        authors = author_groups.get(primary_language, [])
        if not authors:
            authors = next(
                (group for group in author_groups.values() if group),
                [],
            )
        alternative_authors = [
            group
            for group in author_groups.values()
            if group and group != authors
        ]
        venues = self._localized_texts(entry, "material_title")
        links = self._localized_texts(entry, "article_link")
        venue = self._preferred_value(venues, primary_language)
        url = self._preferred_value(links, primary_language)
        year = self._extract_year(
            element_text(entry.find("atom:pubyear", namespaces=NAMESPACES))
        )
        doi = (
            element_text(entry.find("prism:doi", namespaces=NAMESPACES))
            or element_text(entry.find("atom:doi", namespaces=NAMESPACES))
            or None
        )

        metadata = VerifiedCitationInfo(
            title=title,
            alternative_titles=alternative_titles,
            authors=authors,
            alternative_authors=alternative_authors,
            publication_types=["JournalArticle"],
            year=year,
            venue=venue,
            doi=doi,
            url=url,
            raw_payload=etree.tostring(
                entry,
                encoding="unicode",
            ),
        )
        return metadata, None

    @staticmethod
    def _localized_texts(
        entry: etree._Element,
        field_name: str,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for language in ("ja", "en"):
            value = element_text(
                entry.find(
                    f"atom:{field_name}/atom:{language}",
                    namespaces=NAMESPACES,
                )
            )
            if value:
                result[language] = value
        return result

    @staticmethod
    def _localized_authors(
        entry: etree._Element,
    ) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for language in ("ja", "en"):
            names = [
                name
                for name in (
                    element_text(element)
                    for element in entry.findall(
                        f"atom:author/atom:{language}/atom:name",
                        namespaces=NAMESPACES,
                    )
                )
                if name
            ]
            if names:
                result[language] = names
        return result

    @staticmethod
    def _primary_language(
        input_data: InputData,
        titles: dict[str, str],
        author_groups: dict[str, list[str]],
    ) -> str | None:
        reference = input_data.parsed_data
        languages = [
            language for language in ("ja", "en") if titles.get(language)
        ]
        if not languages:
            return None
        return max(
            languages,
            key=lambda language: calculate_citation_similarity(
                reference.title or "",
                titles[language],
                original_authors=reference.authors,
                found_authors=author_groups.get(language, []),
            ),
        )

    @staticmethod
    def _alternatives(
        values: dict[str, str],
        primary_language: str,
    ) -> list[str]:
        primary = values.get(primary_language)
        return [
            value
            for language, value in values.items()
            if language != primary_language and value != primary
        ]

    @staticmethod
    def _preferred_value(
        values: dict[str, str],
        primary_language: str,
    ) -> str:
        return values.get(primary_language) or next(iter(values.values()), "")
