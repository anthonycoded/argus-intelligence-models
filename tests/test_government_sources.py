import json
import pytest
from src.government_sources import allowed_url, parse_feed_file, write_discovery, prepare_candidate

RSS = '''<?xml version="1.0"?><rss version="2.0"><channel><title>Test</title>
<item><title>Naval operations near Taiwan</title><link>https://www.defense.gov/News/Article/123</link><pubDate>Sun, 22 Nov 2026 15:00:00 GMT</pubDate></item>
<item><title>External redirect</title><link>https://defense.gov.evil.example/story</link></item>
<item><title>Duplicate</title><link>https://www.defense.gov/News/Article/123</link></item>
</channel></rss>'''
ATOM = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Security report</title><link href="https://www.gao.gov/products/gao-26-123" rel="alternate"/><updated>2026-11-22T00:00:00Z</updated></entry></feed>'''


def test_url_allowlist():
    assert allowed_url("https://www.defense.gov/News/")
    assert allowed_url("https://gao.gov/products/x")
    assert not allowed_url("http://defense.gov/news")
    assert not allowed_url("https://defense.gov.evil.example/")
    assert not allowed_url("https://evil.example/defense.gov")
    assert not allowed_url("https://user@defense.gov/a")
    assert not allowed_url("https://defense.gov:444/x")


def test_rss_discovery_filters_and_dedupes(tmp_path):
    source = tmp_path / "rss.xml"
    source.write_text(RSS, encoding="utf-8")
    rows, result = parse_feed_file(source, "2026-11-22T10:00:00Z")
    assert result == {"total": 3, "accepted": 1, "unsupported_host": 1, "invalid": 0, "duplicate": 1}
    assert rows[0]["review_status"] == "discovered_unreviewed"
    assert "article_text" not in rows[0] and "label" not in rows[0]


def test_atom_discovery(tmp_path):
    source = tmp_path / "atom.xml"
    source.write_text(ATOM, encoding="utf-8")
    rows, counts = parse_feed_file(source)
    assert counts["accepted"] == 1
    assert rows[0]["published_at_raw"] == "2026-11-22T00:00:00Z"


def test_dtd_and_size_rejected(tmp_path):
    path = tmp_path / "feed.xml"
    path.write_text('<!DOCTYPE rss [<!ENTITY x "foo">]><rss/>', encoding="utf-8")
    with pytest.raises(ValueError, match="DOCTYPE"):
        parse_feed_file(path)
    path.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="2 MiB"):
        parse_feed_file(path)


def test_preparation_is_separate_and_requires_text(tmp_path):
    source = tmp_path / "feed.xml"
    source.write_text(RSS, encoding="utf-8")
    rows, _ = parse_feed_file(source)
    discovery = tmp_path / "discovery.jsonl"
    write_discovery(rows, discovery)
    with pytest.raises(FileExistsError):
        write_discovery(rows, discovery)
    text_path = tmp_path / "source.txt"
    text_path.write_text("short", encoding="utf-8")
    with pytest.raises(ValueError, match="at least 100"):
        prepare_candidate(discovery, rows[0]["discovery_id"], text_path, "human_summary", "original summary", "group-1", tmp_path / "batch.jsonl")
    text_path.write_text("This is a carefully reviewed and independently written summary of an official report. " * 3, encoding="utf-8")
    batch = tmp_path / "batch.jsonl"
    result = prepare_candidate(discovery, rows[0]["discovery_id"], text_path, "human_summary", "original summary", "group-1", batch)
    assert result["prepared"] == 1
    candidate = json.loads(batch.read_text(encoding="utf-8"))
    assert candidate["event_group_id"] == "group-1"
    assert candidate["content_type"] == "human_summary"
    assert "unverified" in candidate["rights_note"]
    assert "label" not in candidate


def test_invalid_feed_rejected(tmp_path):
    path = tmp_path / "other.xml"
    path.write_text("<foo></foo>", encoding="utf-8")
    with pytest.raises(ValueError, match="RSS"):
        parse_feed_file(path)
