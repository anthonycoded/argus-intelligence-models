import json
from pathlib import Path

import pytest

from src.feed_automation import collect, load_config, priority, validate_feed_url


def xml(items):
    return ("<rss version='2.0'><channel>" + ''.join(
        f"<item><title>{title}</title><link>https://www.navy.mil/item/{i}</link></item>"
        for i, title in enumerate(items)
    ) + "</channel></rss>").encode()


def test_config_validation(tmp_path):
    config = tmp_path / 'feeds.json'
    config.write_text(json.dumps({'feeds': [{'id': 'navy', 'url': 'https://www.navy.mil/rss.xml'}]}))
    assert load_config(config)[0]['id'] == 'navy'


def test_url_rejects_redirect_attack_domains():
    for url in ('http://www.navy.mil/rss', 'https://navy.mil.evil.test/rss',
                'https://user@navy.mil/rss', 'https://127.0.0.1/feed',
                'https://www.navy.mil:8080/rss', 'https://www.navy.mil/x#fragment'):
        with pytest.raises(ValueError):
            validate_feed_url(url)


def test_incremental_and_prioritization(tmp_path):
    kwargs = {'feeds': [{'id': 'navy', 'url': 'https://www.navy.mil/rss'}],
              'state': tmp_path / 'seen.json', 'feed_dir': tmp_path / 'incoming',
              'fetcher': lambda _: xml(['Chinese naval operations near Taiwan', 'Navy graduation']),
              'low_sample_pct': 100, 'now': '2026-11-22T12:00:00Z'}
    first = collect(**kwargs, output=tmp_path / 'one.jsonl')
    assert first['new'] == 2 and first['high_priority'] == 1
    rows = [json.loads(line) for line in (tmp_path/'one.jsonl').read_text().splitlines()]
    assert all(x['review_status'] == 'discovered_unreviewed' for x in rows)
    assert all(x['selected_for_review'] for x in rows)
    again = collect(**kwargs, output=tmp_path / 'two.jsonl')
    assert again['new'] == 0 and again['previously_seen'] == 2


def test_duplicate_cross_feeds(tmp_path):
    feeds = [{'id': 'a', 'url': 'https://www.navy.mil/a'}, {'id': 'b', 'url': 'https://www.navy.mil/b'}]
    result = collect(feeds, output=tmp_path/'out', state=tmp_path/'state', feed_dir=tmp_path/'xml',
                     fetcher=lambda _: xml(['Taiwan exercise']))
    assert result['new'] == 1 and result['duplicate_in_batch'] == 1


def test_failure_does_not_mark_seen(tmp_path):
    def broken(_):
        raise ValueError('offline')
    result = collect([{'id': 'navy', 'url': 'https://www.navy.mil/rss'}], output=tmp_path/'out',
                     state=tmp_path/'state', feed_dir=tmp_path/'xml', fetcher=broken)
    assert result['new'] == 0 and 'navy' in result['feed_errors']
    assert json.loads((tmp_path/'state').read_text())['seen'] == []


def test_output_never_overwritten(tmp_path):
    out = tmp_path / 'out'
    out.write_text('keep')
    with pytest.raises(FileExistsError):
        collect([], output=out, state=tmp_path/'state', feed_dir=tmp_path/'xml')
    assert out.read_text() == 'keep'


def test_sampling_is_deterministic():
    assert priority('Routine ceremony')[0] == 'low'
    assert priority('Taiwan Strait deployment')[0] == 'high'
