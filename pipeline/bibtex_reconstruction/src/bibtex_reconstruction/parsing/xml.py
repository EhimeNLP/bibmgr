"""Strict XML parsing helpers for bibliographic clients."""

from __future__ import annotations

from lxml import etree


def parse_xml(source: bytes) -> etree._Element:
    """Parse XML without network access, DTD loading, or entity expansion."""

    parser = etree.XMLParser(
        load_dtd=False,
        no_network=True,
        recover=False,
        remove_comments=True,
        resolve_entities=False,
        huge_tree=False,
    )
    return etree.fromstring(source, parser=parser)


def element_text(element: etree._Element | None) -> str:
    """Return the complete stripped text content of one XML element."""

    if element is None:
        return ""
    return "".join(element.itertext()).strip()
