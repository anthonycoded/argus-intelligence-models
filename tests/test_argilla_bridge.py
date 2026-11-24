"""Offline synthetic integration tests; no SDK, Docker, network or models needed."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from src import argilla_bridge as b
from src.global_io import digest, encoded, read_object
from src.global_review import attest_rights, history, load_approval

USER = '12345678-1234-4234-8234-123456789abc'


class Mapping(dict):
    def to_dict(self):
        return dict(self)


class Responses(list):
    def __getitem__(self, key):
        return [v for v in self if v.question_name == key]


class Record:
    def __init__(self, id, fields, metadata, responses=()):
        self.id, self.fields, self.metadata = id, Mapping(fields), Mapping(metadata)
        self.responses = Responses(responses)


class RemoteRecords(list):
    def log(self, rows):
        self.extend(rows)


@pytest.fixture
def bridge(global_case, tmp_path, monkeypatch):
    c = global_case
    row = {'candidate_id': 'candidate-'+'a'*64, 'source_id': c['metadata']['source_id'],
           'publisher': c['metadata']['publisher'], 'article_title': c['metadata']['article_title'],
           'published_at': c['metadata']['published_at'], 'published_at_raw': c['metadata']['published_at_raw'],
           'collected_at': c['metadata']['collected_at'], 'sampling': {'seed': 42, 'selection_reasons': ['synthetic']}}
    sample = tmp_path/'sample'
    sample.mkdir()
    (sample/'manifest.json').write_bytes(encoded({'synthetic': True}))
    monkeypatch.setattr(b, 'load_sample', lambda path: ({}, [deepcopy(row)]))
    monkeypatch.setattr('src.global_sampling.load_sample', lambda path: ({}, [deepcopy(row)]))
    root = tmp_path/'bridge'
    b.initialize(root, sample, c['root'])
    remote = SimpleNamespace(records=RemoteRecords())
    client = SimpleNamespace(users=lambda id: SimpleNamespace(id=UUID(USER), username='actual-human') if id == USER else None)
    return {**c, 'bridge': root, 'sample': sample, 'row': row, 'remote': remote, 'client': client}


def attach(c):
    return b.attach(c['bridge'], c['row']['candidate_id'], c['text_file'], 'human_summary', c['metadata']['rights_note'])


def answers(annotation):
    return {'domains': annotation['domains'], 'defense_event_types': annotation['defense_event_types'] or ['none'],
            'rationale': annotation['rationale'], 'event_coverage': annotation['event_coverage'],
            'details': json.dumps({k: annotation[k] for k in b.DETAIL_FIELDS})}


def submit(c, values=None, status='submitted', user=USER):
    b.import_records(c['bridge'], c['remote'], SimpleNamespace(Record=Record))
    _, items, heads = b.records(c['bridge'])
    head = heads[c['row']['candidate_id']]
    remote = next(r for r in c['remote'].records if r.id == head)
    remote.responses = Responses(SimpleNamespace(question_name=k, value=v, user_id=user, status=status)
                                 for k, v in (values or answers(c['annotation'])).items())
    ids = b.export_responses(c['bridge'], c['remote'], c['client'])['submissions']
    # Content hashes are sorted for reproducible exports, not by recency. Select
    # the intended record/author, regardless of JSON formatting/hash order.
    matches = [ident for ident in ids
               if b._read(c['bridge'], 'submissions', ident, 'submission-')['record_id'] == head
               and b._read(c['bridge'], 'submissions', ident, 'submission-')['reviewer_id'] == user]
    assert len(matches) == 1
    return matches[0]


def test_queue_init_and_import_idempotent_metadata_only(bridge):
    c = bridge
    b.initialize(c['bridge'], c['sample'], c['root'])
    assert b.import_records(c['bridge'], c['remote'], SimpleNamespace(Record=Record))['added'] == 1
    assert b.import_records(c['bridge'], c['remote'], SimpleNamespace(Record=Record))['added'] == 0
    record = c['remote'].records[0]
    assert record.metadata['candidate_id'] == c['row']['candidate_id']
    assert 'PENDING CONTENT' in record.fields['text']
    assert b.reconcile(c['bridge'])['eligibility']['eligible_for_future_dataset'] == 0


def test_pending_content_may_be_drafted_but_not_staged(bridge):
    submission = submit(bridge)
    with pytest.raises(ValueError, match='Pending content'):
        b.stage(bridge['bridge'], submission)
    assert not (bridge['root']/'approvals').exists()


def test_attach_versions_and_preserves_previous_representation(bridge):
    c = bridge
    _, old, _ = b.records(c['bridge'])
    ident = attach(c)
    assert attach(c) == ident
    _, new, heads = b.records(c['bridge'])
    assert len(new) == 2 and old.items() <= new.items()
    assert heads[c['row']['candidate_id']] == ident
    ref = new[ident]['source']
    assert ref['content_revision_sha256'] == digest(c['text_file'].read_bytes())
    assert not (c['root']/'rights').exists()


def test_export_staging_review_and_approval_boundaries(bridge):
    c = bridge
    attach(c)
    submission = submit(c)
    assert submit(c) == submission
    staged = b.stage(c['bridge'], submission)
    assert b.stage(c['bridge'], submission) == staged
    assert len(list((c['root']/'drafts').iterdir())) == 1
    assert not (c['root']/'approvals').exists()
    with pytest.raises(ValueError, match='confirm-review'):
        b.review(c['bridge'], submission, USER)
    reviewed = b.review(c['bridge'], submission, USER, True)
    assert b.reconcile(c['bridge'])['submissions'][0]['aic_state'] == 'reviewed'
    with pytest.raises(ValueError, match='confirm-human-review'):
        b.approve_review(c['bridge'], reviewed, USER)
    approval = b.approve_review(c['bridge'], reviewed, USER, True)
    assert b.approve_review(c['bridge'], reviewed, USER, True) == approval
    assert load_approval(c['root'], approval)['reviewed_by'] == 'argilla:'+USER+':actual-human'
    assert b.reconcile(c['bridge'])['submissions'][0]['aic_state'] == 'approved'
    assert b.reconcile(c['bridge'])['eligibility']['eligible_for_future_dataset'] == 0


@pytest.mark.parametrize('status', ['draft', 'discarded'])
def test_unsubmitted_responses_never_stage(bridge, status):
    attach(bridge)
    submission = submit(bridge, status=status)
    with pytest.raises(ValueError, match='Only submitted'):
        b.stage(bridge['bridge'], submission)


@pytest.mark.parametrize('mutation', ['other', 'country', 'offset', 'hash', 'none', 'incomplete', 'event', 'native', 'date', 'target'])
def test_schema_and_evidence_validation(bridge, mutation):
    c = bridge
    attach(c)
    article = deepcopy(c['annotation'])
    if mutation == 'other':
        article['domains'].append('other')
    elif mutation == 'country':
        article['countries'][0]['code'] = 'ZZ'
    elif mutation == 'offset':
        article['evidence'][0]['end'] -= 1
    elif mutation == 'hash':
        article['evidence'][0]['content_revision_sha256'] = '0'*64
    elif mutation == 'event':
        article['events'][0]['defense_event_types'] = ['defense_other', 'military_exercise']
    elif mutation == 'date':
        article['event_date'] = '2026-02-30'
    elif mutation == 'target':
        article['evidence'][0]['target'] = '/invented/claim'
    values = answers(article)
    if mutation == 'none':
        values['defense_event_types'].append('none')
    elif mutation == 'incomplete':
        del values['details']
    elif mutation == 'native':
        values['evidence_spans'] = [{'start': 99999, 'end': 100000, 'label': 'support'}]
    submission = submit(c, values)
    with pytest.raises((ValueError, TypeError)):
        b.stage(c['bridge'], submission)
    assert not (c['root']/'drafts').exists()


def test_multidomain_article_and_individual_events_preserved(bridge):
    c = bridge
    article = deepcopy(c['annotation'])
    article['domains'].append('economics')
    article['event_coverage'] = 'partial'
    article['event_coverage_note'] = 'Trade agreement remains article level'
    article['evidence'].append({**article['evidence'][0], 'target': '/domains/1'})
    mapped = b.map_answers(answers(article), c['text'], digest(c['text_file'].read_bytes()))
    assert mapped == article


def test_unknown_and_mismatched_reviewer(bridge):
    c = bridge
    attach(c)
    with pytest.raises(ValueError, match='Unknown Argilla reviewer'):
        submit(c, user='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
    submission = submit(c)
    with pytest.raises(ValueError, match='attribution'):
        b.review(c['bridge'], submission, 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', True)


@pytest.mark.parametrize('mutation', ['fields', 'metadata', 'id', 'sample', 'artifact', 'policy'])
def test_binding_and_tamper_rejection(bridge, mutation, monkeypatch):
    c = bridge
    b.import_records(c['bridge'], c['remote'], SimpleNamespace(Record=Record))
    r = c['remote'].records[0]
    if mutation == 'fields':
        r.fields['text'] = 'forged'
    elif mutation == 'metadata':
        r.metadata['candidate_id'] = 'forged'
    elif mutation == 'id':
        r.id = 'record-'+'0'*64
    elif mutation == 'sample':
        (c['sample']/'manifest.json').write_bytes(b'{}')
    elif mutation == 'artifact':
        path = next((c['bridge']/'records').glob('*/data.json'))
        path.write_bytes(path.read_bytes()+b' ')
        # Canonical document hash intentionally ignores harmless whitespace.
        obj = read_object(path)
        obj['candidate']['source_id'] = 'https://forged.example/article'
        path.write_bytes(encoded(obj))
    else:
        original = b.contract
        monkeypatch.setattr(b, 'contract', lambda: {**original(), 'schema_version': 'changed'})
    with pytest.raises((ValueError, KeyError)):
        b.export_responses(c['bridge'], c['remote'], c['client'])


def test_content_update_stales_submission_without_deleting_history(bridge):
    c = bridge
    first = attach(c)
    submission = submit(c)
    c['text_file'].write_bytes(c['text_file'].read_bytes()+b'\nNew permitted revision.')
    second = attach(c)
    assert first != second
    with pytest.raises(ValueError, match='Stale'):
        b.stage(c['bridge'], submission)
    assert b.reconcile(c['bridge'])['submissions'][0]['blocked']


def test_revisions_keep_approval_history_and_restricted_rights(bridge):
    c = bridge
    attach(c)
    submission = submit(c)
    first = b.approve_review(c['bridge'], b.review(c['bridge'], submission, USER, True), USER, True)
    original = (c['root']/'approvals'/first/'approval.json').read_bytes()
    changed = answers(c['annotation'])
    changed['rationale'] = 'Corrected actual human rationale'
    second_submission = submit(c, changed)
    second = b.approve_review(c['bridge'], b.review(c['bridge'], second_submission, USER, True, first), USER, True)
    assert load_approval(c['root'], second)['supersedes'] == first
    assert (c['root']/'approvals'/first/'approval.json').read_bytes() == original
    assert len(history(c['root'])[0]) == 2
    attest_rights(c['root'], c['source'], 'restricted', 'Synthetic restriction', 'rights-reviewer', True)
    report = b.reconcile(c['bridge'])['eligibility']
    assert report['eligible_for_future_dataset'] == 0
    assert report['sources'][c['source']]['rights_status'] == 'restricted'


@pytest.mark.parametrize('url', ['https://external.example', 'http://localhost:6900', 'http://127.0.0.1:6900/path', 'http://a:b@127.0.0.1:6900'])
def test_remote_servers_rejected_before_sdk_import(url):
    with pytest.raises(ValueError, match='Only local'):
        b.local_client(url)


def test_withdrawn_or_replaced_response_cannot_be_approved(bridge):
    c = bridge
    attach(c)
    submitted = submit(c)
    reviewed = b.review(c['bridge'], submitted, USER, True)
    submit(c, status='draft')
    with pytest.raises(ValueError, match='Stale/withdrawn'):
        b.approve_review(c['bridge'], reviewed, USER, True)
    assert not (c['root']/'approvals').exists()


def test_settings_comparison_normalizes_server_ids_and_null_descriptions_only():
    expected = {'required':True,'settings':{'options':[{'value':'defense'}]}}
    remote = {**deepcopy(expected),'id':'server-generated','description':None}
    remote['settings']['options'][0]['description'] = None
    assert b._settings_signature(remote)==b._settings_signature(expected)
    remote['required'] = False
    assert b._settings_signature(remote)!=b._settings_signature(expected)


def test_forged_staging_reviewer_receipt_is_rejected(bridge):
    c = bridge
    attach(c)
    submission = submit(c)
    b.stage(c['bridge'], submission)
    path = next((c['bridge']/'stages').glob('*/data.json'))
    receipt = read_object(path)
    receipt['reviewer_username'] = 'forged-reviewer'
    path.write_bytes(encoded(receipt))
    with pytest.raises(ValueError, match='receipt mismatch'):
        b.review(c['bridge'], submission, USER, True)
    assert b.reconcile(c['bridge'])['submissions'][0]['blocked']


@pytest.mark.parametrize('kind', ['mixed_status', 'duplicate', 'unknown_question', 'malformed_details'])
def test_malformed_server_answers_fail_closed(bridge, kind):
    c = bridge
    attach(c)
    if kind == 'malformed_details':
        values = answers(c['annotation'])
        values['details'] = '{"countries":[],"countries":[]}'
        submission = submit(c, values)
        with pytest.raises(ValueError):
            b.stage(c['bridge'], submission)
        return
    submit(c)
    remote = c['remote'].records[-1]
    # Find the current attached record independently of sorted record order.
    remote = next(r for r in c['remote'].records if r.metadata['state']=='content_attached')
    if kind == 'mixed_status':
        list.__getitem__(remote.responses, 0).status = 'draft'
    elif kind == 'duplicate':
        remote.responses.append(deepcopy(list.__getitem__(remote.responses, 0)))
    else:
        remote.responses.append(SimpleNamespace(question_name='forged', value='x', user_id=USER, status='submitted'))
    with pytest.raises(ValueError):
        b.export_responses(c['bridge'], c['remote'], c['client'])


def test_real_sample_to_bridge_content_and_staging(global_case, tmp_path):
    from src.global_discovery import rank_global
    from src.global_sampling import sample_ranking
    c = global_case
    discovery = tmp_path/'discoveries.jsonl'
    discovery.write_bytes(encoded({**{k: c['metadata'][k] for k in ('source_id','publisher','article_title','published_at','published_at_raw','collected_at')},
                                   'source_region':'Africa','language':'en'})+b'\n')
    ranked, sample, root, store = [tmp_path/n for n in ('ranked','sample','bridge','store')]
    rank_global([discovery], ranked, tmp_path/'cache', revision='a'*40,
                encoder=lambda texts:[[1.,0.] for _ in texts], encoder_id='synthetic-2p-v1')
    sample_ranking(ranked, sample, {'schema_version':'aic-global-sampling-v1','seed':42,
                                  'per_stratum':1,'publisher_cap':1,'region_cap':1,'max_total':1})
    b.initialize(root, sample, store)
    _, _, heads = b.records(root)
    candidate = next(iter(heads))
    attached = b.attach(root, candidate, c['text_file'], 'human_summary', 'Synthetic test handling basis')
    assert b.attach(root, candidate, c['text_file'], 'human_summary', 'Synthetic test handling basis') == attached
    record = b.records(root)[1][attached]
    assert record['source']['content_revision_sha256']==digest(c['text_file'].read_bytes())
    assert len(list((store/'intake').iterdir()))==1
