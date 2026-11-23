import copy
import json
from pathlib import Path

import pytest

from src.global_taxonomy import load_taxonomy, validate_global_annotation, validate_jsonl

TAX = load_taxonomy(Path(__file__).resolve().parents[1] / 'taxonomies/global_intelligence_v1.json')


def sample():
    return {
        'record_id':'global-example-001', 'source_id':'https://www.navy.mil/example',
        'event_group_id':'mavi-balina-2026', 'taxonomy_version':'aic-global-v1',
        'annotation_status':'human_verified', 'reviewed_by':'human-001',
        'domains':['defense'], 'defense_event_types':['military_exercise','military_diplomacy'],
        'countries':[{'code':'US','role':'participant'},{'code':'TR','role':'host'}],
        'organizations':['U.S. Navy','Turkish Navy'], 'event_location':'Türkiye',
        'event_date':None, 'evidence_status':'reported',
        'evidence':[{'field':'defense_event_types','text':'Official report describes a multinational naval exercise.'}],
        'rationale':'Multinational anti-submarine exercise.'
    }


def test_valid_global_defense():
    assert validate_global_annotation(sample(), TAX)['domains']==['defense']


def test_no_country_or_taiwan_required():
    row=sample(); row['countries']=[]; row['event_location']=None
    assert validate_global_annotation(row,TAX)


def test_multiple_domains_allowed():
    row=sample(); row['domains']=['defense','economics']
    assert validate_global_annotation(row,TAX)


def test_non_defense_no_event_tags():
    row=sample(); row['domains']=['economics']; row['defense_event_types']=[]
    assert validate_global_annotation(row,TAX)


def test_defense_tags_require_domain():
    row=sample(); row['domains']=['economics']
    with pytest.raises(ValueError,match='require defense'):
        validate_global_annotation(row,TAX)


def test_unknown_event_rejected():
    row=sample(); row['defense_event_types']=['space_aliens']
    with pytest.raises(ValueError,match='unknown'):
        validate_global_annotation(row,TAX)


def test_verified_requires_reviewer():
    row=sample(); row['reviewed_by']=None
    with pytest.raises(ValueError,match='reviewed_by'):
        validate_global_annotation(row,TAX)


def test_pending_cannot_claim_reviewer():
    row=sample(); row['annotation_status']='pending'
    with pytest.raises(ValueError,match='pending must not'):
        validate_global_annotation(row,TAX)


def test_policy_mismatch():
    row=sample(); row['taxonomy_version']='aic-global-v2'
    with pytest.raises(ValueError,match='mismatch'):
        validate_global_annotation(row,TAX)


def test_duplicate_country_roles_rejected():
    row=sample(); row['countries'].append(copy.deepcopy(row['countries'][0]))
    with pytest.raises(ValueError,match='duplicate country'):
        validate_global_annotation(row,TAX)


def test_annotated_defense_needs_event():
    row=sample(); row['defense_event_types']=[]
    with pytest.raises(ValueError,match='at least one'):
        validate_global_annotation(row,TAX)


def test_jsonl_duplicate_id_rejected(tmp_path):
    file=tmp_path/'sample.jsonl'
    file.write_text(json.dumps(sample())+'\n'+json.dumps(sample())+'\n',encoding='utf8')
    with pytest.raises(ValueError,match='duplicate record_id'):
        validate_jsonl(file,TAX)


def test_existing_pilot_unmodified():
    # Global annotation validation is an independent schema, not a rewrite of
    # src/schema.py or the topic-conditioned record format.
    from src.schema import LABELS
    assert LABELS == ('unrelated','partially_relevant','relevant')
