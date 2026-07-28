from typing import Optional, Tuple

from lxml import etree

from api_clients.base_client import BaseAPIClient
from core.xml_utils import element_text, parse_xml
from models import InputData, VerifiedCitationInfo

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

        response = self._make_request(params=params)
        if not response:
            return None, None

        root = parse_xml(response.content)
        status = element_text(
            root.find("atom:result/atom:status", namespaces=NAMESPACES)
        )
        if status and status != "0":
            return None, None

        entry = root.find("atom:entry", namespaces=NAMESPACES)
        if entry is None:
            return None, None

        title = self._localized_text(entry, "article_title")
        venue = self._localized_text(entry, "material_title")
        url = self._localized_text(entry, "article_link")
        authors = self._authors(entry)
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
            authors=authors,
            year=year,
            venue=venue,
            doi=doi,
            url=url,
        )
        return metadata, None

    @staticmethod
    def _localized_text(
        entry: etree._Element,
        field_name: str,
    ) -> str:
        for language in ("ja", "en"):
            value = element_text(
                entry.find(
                    f"atom:{field_name}/atom:{language}",
                    namespaces=NAMESPACES,
                )
            )
            if value:
                return value
        return ""

    @staticmethod
    def _authors(entry: etree._Element) -> list[str]:
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
                return names
        return []
