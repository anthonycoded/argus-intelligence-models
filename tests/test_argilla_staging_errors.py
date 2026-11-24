"""Privacy-safe diagnostics and article-only economics staging regression cases."""
from copy import deepcopy
import json

import pytest

from tests.test_argilla_bridge import bridge, attach, answers, submit
from src import argilla_bridge as b
from src.global_io import digest


def economic_article(c):
    text=c['text']
    start=text.index('A trade agreement')
    end=start+len('A trade agreement cut tariffs.')
    return {'schema_version':'aic-global-annotation-v2','domains':['economics'],
            'defense_event_types':[],'countries':[],'organizations':[],
            'event_date':None,'event_location':None,'evidence_status':'unknown',
            'rationale':'Synthetic reviewer identifies a trade-policy development.',
            'event_coverage':'not_enumerated','event_coverage_note':'Article-level domain annotation; individual events not enumerated.',
            'events':[], 'evidence':[{'target':'/domains/0',
                'content_revision_sha256':digest(c['text_file'].read_bytes()),
                'start':start,'end':end,'quote':text[start:end],'attribution':'Synthetic test source'}]}


@pytest.mark.parametrize('value,expected',[
    ('','details: empty'),(' \t\r\n','details: empty'),
    ('Private reviewer prose with confidential text','details: invalid JSON at line 1, column 1'),
    ('```json\n{}\n```','details: invalid JSON'),
    ('{"events": }','details: invalid JSON'),
    ('[]','details: expected one JSON object'),('null','details: expected one JSON object'),
    ('"private text"','details: expected one JSON object'),
    (None,'details: expected JSON object text'),
    ('{"private sensitive key":1,"private sensitive key":2}','duplicate keys'),
    ('{"private sensitive key":NaN}','non-finite'),
])
def test_details_diagnostics_never_echo_values_or_private_keys(value,expected):
    with pytest.raises(ValueError) as caught:
        b.parse_details(value)
    message=str(caught.value)
    assert expected in message
    assert 'examples/argilla_details_TEMPLATE.json' in message
    assert 'private sensitive key' not in message and 'Private reviewer prose' not in message
    assert 'confidential text' not in message


def test_missing_and_extra_details_fields_actionable_without_echoing_keys():
    with pytest.raises(ValueError) as caught:
        b.parse_details('{"PRIVATE_FIELD_WITH_TEXT":"private body"}')
    message=str(caught.value)
    assert 'events' in message and 'evidence' in message and 'Remove 1 unexpected field' in message
    assert 'PRIVATE_FIELD' not in message and 'private body' not in message


def test_economics_only_without_individual_events_stages_idempotently(bridge):
    c=bridge
    attach(c)
    article=economic_article(c)
    submission=submit(c,answers(article))
    before=deepcopy([vars(r) for r in c['remote'].records])
    first=b.stage(c['bridge'],submission)
    assert b.stage(c['bridge'],submission)==first
    assert submit(c,answers(article))==submission
    assert b.stage(c['bridge'],submission)==first
    assert [vars(r) for r in c['remote'].records]==before
    assert not (c['root']/'approvals').exists()


def test_partial_without_events_prompts_article_level_scope(bridge):
    c=bridge
    attach(c)
    article=economic_article(c)
    article['event_coverage']='partial'
    submission=submit(c,answers(article))
    with pytest.raises(ValueError,match='event_coverage: partial.*not_enumerated'):
        b.stage(c['bridge'],submission)


def test_article_only_economics_still_requires_evidence(bridge):
    c=bridge
    attach(c)
    article=economic_article(c)
    article['evidence']=[]
    submission=submit(c,answers(article))
    with pytest.raises(ValueError,match='details.evidence: nonempty'):
        b.stage(c['bridge'],submission)


@pytest.mark.parametrize('mutation',['hash','quote','offset','target'])
def test_article_only_economics_never_bypasses_evidence_integrity(bridge,mutation):
    c=bridge
    attach(c)
    article=economic_article(c)
    evidence=article['evidence'][0]
    if mutation=='hash': evidence['content_revision_sha256']='0'*64
    elif mutation=='quote': evidence['quote']='forged synthetic quote'
    elif mutation=='offset': evidence['end']+=1
    else: evidence['target']='/invented/field'
    submission=submit(c,answers(article))
    with pytest.raises(ValueError,match='Forged/stale|Unknown/forged'):
        b.stage(c['bridge'],submission)
    assert not (c['root']/'drafts').exists()


def test_changed_registered_content_blocks_even_valid_economics_form(bridge):
    c=bridge
    attach(c)
    submission=submit(c,answers(economic_article(c)))
    path=c['root']/'sources'/c['source']/'content.utf8'
    path.write_bytes(path.read_bytes()+b' altered')
    with pytest.raises(ValueError):
        b.stage(c['bridge'],submission)


def test_invalid_details_repeated_export_preserves_existing_draft_and_submission(bridge):
    c=bridge
    prior=submit(c,status='draft')
    attach(c)
    values=answers(economic_article(c));values['details']='not supplemental JSON'
    current=submit(c,values)
    before=deepcopy([vars(r) for r in c['remote'].records])
    first=b.export_responses(c['bridge'],c['remote'],c['client'])
    assert b.export_responses(c['bridge'],c['remote'],c['client'])==first
    assert set(first['submissions'])=={prior,current}
    with pytest.raises(ValueError,match='details: invalid JSON'):
        b.stage(c['bridge'],current)
    assert [vars(r) for r in c['remote'].records]==before


def test_details_array_type_errors_identify_the_field(bridge):
    values=answers(economic_article(bridge))
    details=json.loads(values['details']);details['events']='not a list'
    with pytest.raises(ValueError,match='details.events: expected a JSON array'):
        b.parse_details(json.dumps(details))
