import json
from pathlib import Path

from src.candidate_import import canonical_source, import_batch, quality_report

TOPIC = Path('topics/taiwan_military_v2.json')


def candidate(n=1):
    return {
        'event_group_id': 'event-test', 'source_id': f'https://example.org/event/{n}?utm_source=test',
        'collected_at': '2026-11-22T00:00:00Z', 'article_title': f'Title {n}',
        'article_text': f'This is authorized example content for test case {n}.',
        'content_type': 'human_summary', 'rights_note': 'Synthetic test fixture'
    }


def paths(tmp_path):
    return (tmp_path/'queue', tmp_path/'approved.jsonl', tmp_path/'provenance')


def write_batch(tmp_path, records):
    p = tmp_path/'batch.jsonl'
    p.write_text(''.join(json.dumps(r)+'\n' for r in records), encoding='utf-8')
    return p


def test_two_distinct_candidates_queued_without_approval(tmp_path):
    q, a, p = paths(tmp_path)
    result = import_batch(write_batch(tmp_path, [candidate(1), candidate(2)]), TOPIC, q, a, p)
    assert result['queued'] == 2
    assert not a.exists()
    assert len(list(q.glob('*.json'))) == 2
    assert len(list(p.glob('aic1-*.json'))) == 2


def test_duplicate_url_after_tracking_cleanup(tmp_path):
    q, a, p = paths(tmp_path)
    a1 = candidate()
    a2 = candidate()
    a2['source_id'] = 'https://example.org/event/1?utm_campaign=abc'
    result = import_batch(write_batch(tmp_path, [a1, a2]), TOPIC, q, a, p)
    assert result['queued'] == 1 and result['duplicate'] == 1


def test_duplicate_text_different_urls(tmp_path):
    q, a, p = paths(tmp_path)
    a1, a2 = candidate(1), candidate(2)
    a2['article_text'] = a1['article_text'].upper()
    result = import_batch(write_batch(tmp_path, [a1, a2]), TOPIC, q, a, p)
    assert result['duplicate'] == 1


def test_bad_rights_note_does_not_queue(tmp_path):
    q, a, p = paths(tmp_path)
    x = candidate()
    x['rights_note'] = ''
    result = import_batch(write_batch(tmp_path, [x]), TOPIC, q, a, p)
    assert result['invalid'] == 1
    assert not list(q.glob('*.json'))


def test_report_tracks_pending_provenance(tmp_path):
    q, a, p = paths(tmp_path)
    import_batch(write_batch(tmp_path, [candidate()]), TOPIC, q, a, p)
    result = quality_report(q, a, p)
    assert result['pending'] == 1 and result['approved'] == 0
    assert result['content_types_known'] == {'human_summary': 1}


def test_url_canonicalization():
    assert canonical_source('https://EXAMPLE.org/a/?utm_source=x#part') == 'https://example.org/a'
