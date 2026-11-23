import pytest

from src.government_sources import parse_feed_file
from src.news_feeds import parse


def readers(raw, tmp_path):
    path = tmp_path / "feed.xml"
    path.write_bytes(raw)
    return [lambda: parse_feed_file(path), lambda: parse(raw, "2026-11-22T00:00:00Z")]


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-le", "utf-16-be", "utf-32", "iso-8859-1"])
@pytest.mark.parametrize("declaration", [
    '<!DOCTYPE rss [<!ENTITY probe "expanded">]>',
    '<!DOCTYPE rss SYSTEM "file:///never-read.dtd">',
    '<!DOCTYPE rss [<!ENTITY probe SYSTEM "https://never-contact.example/entity">]>',
    '<!DOCTYPE rss [<!ENTITY % probe SYSTEM "file:///never-read.dtd">%probe;]>',
])
def test_dtd_entity_payloads_rejected_in_all_encodings(tmp_path, encoding, declaration):
    xml = f'<?xml version="1.0" encoding="{encoding}"?>{declaration}<rss><channel/></rss>'
    for read in readers(xml.encode(encoding), tmp_path):
        with pytest.raises(ValueError):
            read()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "iso-8859-1"])
@pytest.mark.parametrize("kind", ["rss", "atom"])
def test_valid_feeds_and_predefined_entities_preserved(tmp_path, encoding, kind):
    for host, reader_index in [("www.navy.mil", 0), ("www.defensenews.com", 1)]:
        if kind == "rss":
            body = f'<rss><channel><item><title>Exercice &amp; défense</title><link>https://{host}/story</link></item></channel></rss>'
        else:
            body = f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Exercice &amp; défense</title><link href="https://{host}/story"/></entry></feed>'
        raw = (f'<?xml version="1.0" encoding="{encoding}"?>' + body).encode(encoding)
        rows, _ = readers(raw, tmp_path)[reader_index]()
        assert rows[0]["article_title"] == "Exercice & défense"


@pytest.mark.parametrize("raw", [b"<rss>&undefined;</rss>", b"<rss>", b"<rss>" + b"<x>" * 130 + b"</x>" * 130 + b"</rss>",
                                  b"<rss>" + b"<x/>" * 20001 + b"</rss>", b"x" * (2 * 1024 * 1024 + 1)])
def test_malformed_and_structurally_unsafe_xml_rejected(tmp_path, raw):
    for read in readers(raw, tmp_path):
        with pytest.raises(ValueError):
            read()
