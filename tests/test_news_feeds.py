import json
import pytest
from src.news_feeds import collect, parse, permitted_url

FEED = b'''<rss version="2.0"><channel><item><title>Chinese naval activity near Taiwan</title><link>https://www.defensenews.com/global/asia-pacific/story-one/</link></item><item><title>European maintenance news</title><link>https://www.defensenews.com/global/europe/story-two/</link></item></channel></rss>'''
URL = 'https://www.defensenews.com/global/asia-pacific/feed/'

def test_allowlisted_feed_and_article_urls():
    assert permitted_url(URL, feed=True)
    assert permitted_url('https://www.defensenews.com/global/europe/story/', feed=False)
    assert not permitted_url('https://www.defensenews.com/global/europe/story/', feed=True)
    for url in ['http://www.defensenews.com/global/asia-pacific/feed/',
                'https://defensenews.com.evil.test/global/asia-pacific/feed/',
                'https://user@www.defensenews.com/global/asia-pacific/feed/',
                'https://127.0.0.1/global/asia-pacific/feed/',
                'https://www.navy.mil/DesktopModules/ArticleCS/RSS.ashx']:
        assert not permitted_url(url, feed=True)

def test_parse_metadata_only():
    records, stats = parse(FEED, '2026-11-22T19:00:00Z')
    assert stats['total'] == 2
    assert len(records) == 2
    assert records[0]['priority'] == 'high'
    assert records[0]['content_type'] == 'metadata_only'
    assert records[0]['review_status'] == 'discovered_unreviewed'
    assert 'article_text' not in records[0]

def test_reject_offsite_articles():
    raw = FEED.replace(b'www.defensenews.com', b'www.bad.test')
    records, counts = parse(raw, '2026-11-22T19:00:00Z')
    assert not records
    assert counts['unsupported_host'] == 2

def test_reject_xml_entities():
    with pytest.raises(ValueError):
        parse(b'<!DOCTYPE rss [<!ENTITY x "unsafe">]><rss/>', '2026-11-22T19:00:00Z')

def test_incremental_state_isolated(tmp_path):
    cfg = dict(url=URL, state=tmp_path/'news_seen.json', fetcher=lambda _: FEED, now='2026-11-22T19:00:00Z')
    first = collect(output=tmp_path/'first.jsonl', **cfg)
    second = collect(output=tmp_path/'second.jsonl', **cfg)
    assert first['new'] == 2
    assert second['new'] == 0 and second['previously_seen'] == 2
    assert json.loads((tmp_path/'news_seen.json').read_text())['schema_version'] == 1
    assert (tmp_path/'first.jsonl').read_text().count('\n') == 2
    assert (tmp_path/'second.jsonl').read_text() == ''

def test_no_output_overwrite(tmp_path):
    path = tmp_path/'existing.jsonl'
    path.write_text('protected')
    with pytest.raises(FileExistsError):
        collect(url=URL, output=path, state=tmp_path/'seen.json', fetcher=lambda _: FEED)
    assert path.read_text() == 'protected'
