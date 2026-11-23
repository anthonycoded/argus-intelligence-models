import json
from pathlib import Path

import pytest

from src.dataset_integrity import (backfill, effective_provenance, snapshot_report,
    submit_policy_review, attest_rights, freeze_snapshot)

TOPIC = Path('topics/taiwan_military_v2.json')


def example():
    return {
        'record_id':'aic1-'+'a'*32, 'event_group_id':'test-event', 'source_id':'https://example.org/story',
        'collected_at':'2026-11-22T00:00:00Z', 'topic':'Chinese military activity near Taiwan',
        'topic_id':'taiwan-military', 'subject_spec':'Sample subject description',
        'article_title':'Test report', 'article_text':'Example text describing an exercise.',
        'label':'relevant', 'label_source':'human_verified', 'rationale':'Qualifying military exercise',
        'annotation_version':'v1.1', 'annotation_policy_version':'aic1-taiwan-v1',
        'criteria':{k:{'assessment':v,'evidence':'Human supplied test evidence'} for k,v in
             [('mandatory_subject','met'),('geography','met'),('material_connection','met'),('exclusion','not_met')]},
    }


def setup(tmp_path):
    approved = tmp_path/'pilot.jsonl'
    approved.write_text(json.dumps(example())+'\n', encoding='utf-8')
    return approved, tmp_path/'provenance', tmp_path/'reviews'


def test_backfill_idempotent_and_unverified(tmp_path):
    approved, prov, _ = setup(tmp_path)
    before = approved.read_bytes()
    assert backfill(approved, prov)['created'] == 1
    assert backfill(approved, prov)['preserved'] == 1
    assert effective_provenance(example()['record_id'], prov)['rights_status'] == 'unverified'
    assert approved.read_bytes() == before


def test_snapshot_initially_blocks_missing_provenance(tmp_path):
    approved, prov, reviews = setup(tmp_path)
    report, rows = snapshot_report(approved, prov, reviews, TOPIC)
    assert not rows and 'missing_provenance' in report['blocked'][example()['record_id']]


def test_backfill_does_not_clear_rights(tmp_path):
    approved, prov, reviews = setup(tmp_path)
    backfill(approved, prov)
    report, _ = snapshot_report(approved, prov, reviews, TOPIC)
    assert 'rights_not_cleared' in report['blocked'][example()['record_id']]
    assert 'policy_review_missing' in report['blocked'][example()['record_id']]


def test_policy_review_requires_explicit_confirmation(tmp_path):
    approved, prov, reviews = setup(tmp_path)
    rf = tmp_path/'review.json'
    rf.write_text(json.dumps({k:example()[k] for k in ('label','rationale','criteria')}))
    with pytest.raises(ValueError, match='Human confirmation'):
        submit_policy_review(example()['record_id'], rf, approved, TOPIC, reviews, 'reviewer', False)
    assert not reviews.exists()


def test_policy_review_preserves_original(tmp_path):
    approved, prov, reviews = setup(tmp_path)
    before = approved.read_bytes()
    rf = tmp_path/'review.json'
    rf.write_text(json.dumps({k:example()[k] for k in ('label','rationale','criteria')}))
    r = submit_policy_review(example()['record_id'], rf, approved, TOPIC, reviews, 'test-reviewer', True)
    assert r['target_policy_version'] == 'aic1-taiwan-v2'
    assert approved.read_bytes() == before
    with pytest.raises(FileExistsError):
        submit_policy_review(example()['record_id'], rf, approved, TOPIC, reviews, 'test-reviewer', True)


def test_eligibility_requires_policy_and_rights(tmp_path):
    approved, prov, reviews = setup(tmp_path)
    backfill(approved, prov)
    rf = tmp_path/'review.json'
    rf.write_text(json.dumps({k:example()[k] for k in ('label','rationale','criteria')}))
    submit_policy_review(example()['record_id'], rf, approved, TOPIC, reviews, 'reviewer', True)
    attest_rights(example()['record_id'], 'cleared', 'Synthetic material written for testing',
                  'human_summary', 'reviewer', approved, prov)
    report, rows = snapshot_report(approved, prov, reviews, TOPIC)
    assert len(rows) == 1
    assert rows[0]['annotation_policy_version'] == 'aic1-taiwan-v2'
    assert not report['training_ready']
    with pytest.raises(ValueError, match='not ready'):
        freeze_snapshot(report, rows, tmp_path/'snapshots')


def test_conflicting_rights_decisions_block(tmp_path):
    approved, prov, reviews = setup(tmp_path)
    backfill(approved, prov)
    for status in ('cleared','restricted'):
        attest_rights(example()['record_id'], status, 'Synthetic test rights decision',
                      'human_summary', 'reviewer', approved, prov)
    assert effective_provenance(example()['record_id'], prov)['rights_status'] == 'conflicting_decisions'
