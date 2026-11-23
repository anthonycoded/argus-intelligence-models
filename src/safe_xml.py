"""Bounded XML parsing with encoding-independent DTD rejection.

Expat decodes the input before invoking doctype; no byte-pattern filtering is
used as a security boundary. Entities requiring declarations cannot be defined
without a DTD. Undefined entities are rejected by the parser itself.
"""
import xml.etree.ElementTree as ET


class _FeedTreeBuilder(ET.TreeBuilder):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.elements = 0

    def doctype(self, name, pubid, system):
        raise ValueError("DOCTYPE/ENTITY declarations not permitted")

    def start(self, tag, attrs):
        self.depth += 1
        self.elements += 1
        if self.depth > 128 or self.elements > 20000:
            raise ValueError("XML structural limit exceeded")
        return super().start(tag, attrs)

    def end(self, tag):
        result = super().end(tag)
        self.depth -= 1
        return result


def parse_xml(raw: bytes, max_bytes: int) -> ET.Element:
    if len(raw) > max_bytes:
        raise ValueError("XML exceeds byte limit")
    try:
        return ET.fromstring(raw, parser=ET.XMLParser(target=_FeedTreeBuilder()))
    except (ET.ParseError, LookupError) as exc:
        raise ValueError(f"Invalid XML: {exc}") from exc
