from core.xml_utils import element_text, parse_xml


def test_xml_parser_does_not_expand_external_entities():
    source = b"""\
<!DOCTYPE feed [
  <!ENTITY external SYSTEM "file:///definitely-not-readable">
]>
<feed>&external;</feed>
"""

    root = parse_xml(source)

    assert element_text(root) == "&external;"
