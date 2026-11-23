import json
from pathlib import Path

import pytest

from src.semantic_ranker import rank, read_discoveries, topic_query


def files(tmp_path):
    topic = tmp_path / 'topic.json'
    topic.write_text(json.dumps({'title':'Taiwan military','mandatory_subject':'Chinese exercises',
                                 'geographic_scope':'Taiwan Strait','material_connection':'Concrete operations'}))
    data = tmp_path / 'records.jsonl'
    records = [
        {'source_id': 'https://example.org/a', 'article_title': 'Chinese naval exercises', 'priority':'low', 'review_status':'discovered_unreviewed'},
        {'source_id': 'https://example.org/b', 'article_title': 'Navy anniversary', 'priority':'low'},
    ]
    data.write_text(''.join(json.dumps(r)+'\n' for r in records))
    return topic, data


def fake(texts):
    return [[1., 0.] if 'Chinese naval' in t or 'Taiwan military' in t else [0.,1.] for t in texts]


def test_rank_and_preserve_metadata(tmp_path):
    topic, data = files(tmp_path)
    out = tmp_path/'out.jsonl'
    result = rank([data], topic, out, tmp_path/'cache', encoder=fake)
    rows = [json.loads(s) for s in out.read_text().splitlines()]
    assert result['ranked'] == 2
    assert rows[0]['source_id'].endswith('/a')
    assert rows[0]['semantic_score'] == 1.0
    assert rows[0]['priority'] == 'low'
    assert rows[0]['review_status'] == 'discovered_unreviewed'
    assert rows[0]['semantic_rank'] == 1


def test_cache_used_second_time(tmp_path):
    topic, data = files(tmp_path)
    cache = tmp_path/'cache'
    rank([data], topic, tmp_path/'first.jsonl', cache, encoder=fake)
    def fail(_):
        raise AssertionError('Model should not rerun')
    result = rank([data], topic, tmp_path/'second.jsonl', cache, encoder=fail)
    assert result['cache_hits'] == 3
    assert result['new_embeddings'] == 0


def test_duplicate_ids_removed(tmp_path):
    topic, data = files(tmp_path)
    result = rank([data, data], topic, tmp_path/'out.jsonl', tmp_path/'cache', encoder=fake)
    assert result['ranked'] == 2
    assert result['duplicates'] == 2


def test_missing_titles_skipped(tmp_path):
    _, data = files(tmp_path)
    with data.open('a') as f:
        f.write(json.dumps({'source_id':'https://example.org/c'})+'\n')
    rows, stats = read_discoveries([data])
    assert len(rows) == 2 and stats['missing_title'] == 1


def test_output_not_overwritten(tmp_path):
    topic, data = files(tmp_path)
    out = tmp_path/'out.jsonl'
    out.write_text('original')
    with pytest.raises(FileExistsError):
        rank([data], topic, out, tmp_path/'cache', encoder=fake)
    assert out.read_text() == 'original'


def test_reject_bad_topic():
    with pytest.raises(ValueError):
        topic_query({'title':'Taiwan'})


def test_corrupt_cache_rejected(tmp_path):
    from src.semantic_ranker import _cache_key
    topic, data = files(tmp_path)
    cache = tmp_path/'cache'
    cache.mkdir()
    query = topic_query(json.loads(topic.read_text()))
    (cache/f'{_cache_key("test-model", query)}.json').write_text('{broken')
    with pytest.raises(ValueError, match='Corrupt embedding cache'):
        rank([data], topic, tmp_path/'out.jsonl', cache, model_name='test-model', encoder=fake)


def test_rank_tiebreak_source_id(tmp_path):
    topic, data = files(tmp_path)
    def same(texts): return [[1,0] for _ in texts]
    rank([data], topic, tmp_path/'out.jsonl', tmp_path/'cache', encoder=same)
    rows = [json.loads(r) for r in (tmp_path/'out.jsonl').read_text().splitlines()]
    assert [r['source_id'] for r in rows] == sorted(r['source_id'] for r in rows)
