"""Disposable metadata-to-approval API integration. No production writes/network."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

from tests.test_argilla_bridge import bridge,USER
from src.review_dashboard import create_app
from src.review_dashboard_service import ReviewService,empty_annotation
from src.global_review import history

ACTOR={'id':USER,'username':'synthetic-reviewer'}


@pytest.fixture
def dashboard(bridge,tmp_path):
    c=bridge
    service=ReviewService(c['bridge'],tmp_path/'dashboard')
    def auth(username,password):
        if username!='reviewer' or password!='fixture-password':raise ValueError('Invalid fixture login')
        return ACTOR
    app=create_app(service,auth,origin='http://testserver')
    client=TestClient(app)
    response=client.post('/api/login',headers={'Origin':'http://testserver'},json={'username':'reviewer','password':'fixture-password'})
    assert response.status_code==200
    client.headers.update({'Origin':'http://testserver','X-AIC-CSRF':response.json()['csrf']})
    return {**c,'argilla_client':c['client'],'service':service,'client':client,'candidate':c['row']['candidate_id'],'app':app}


def request(c,action,body):
    return c['client'].post('/api/candidates/'+c['candidate']+'/'+action,json=body)


def item(c):return c['client'].get('/api/candidates/'+c['candidate']).json()


def content(c):
    before=item(c)
    response=request(c,'attach',{'record_id':before['record_id'],'text':'The consortium\u2019s trade policy cut tariffs. \U0001f600 No additional claims are asserted.',
        'content_type':'human_summary','handling_basis':'Synthetic reviewer-authored fixture only; rights unverified'})
    assert response.status_code==200,response.text
    return response.json()['candidate']


def form():
    a=empty_annotation();a.update(domains=['economics'],event_coverage='not_enumerated',
        event_coverage_note='Article-level synthetic fixture; no events enumerated.',rationale='Trade policy is the reviewed economic development.')
    return a


def mapped(c,article,annotation=None):
    a=form() if annotation is None else deepcopy(annotation)
    text=article['text'];end=text.index('.')+1
    result=request(c,'evidence',{'record_id':article['record_id'],'annotation':a,'start':0,'end':end,
        'quote':text[:end],'targets':['/domains/0'],'attribution':'Synthetic summary','confirmed_mapping':True})
    assert result.status_code==200,result.text
    a['evidence']=[r['evidence'] for r in result.json()['mapped']]
    return a,[r['receipt_id'] for r in result.json()['mapped']]


def save(c,article,a,receipts,work=None,supersedes=None):
    return request(c,'save',{'record_id':article['record_id'],'work_id':work,'annotation':a,
                           'evidence_receipts':receipts,'supersedes':supersedes})


def staged(c):
    article=content(c);a,receipts=mapped(c,article)
    saved=save(c,article,a,receipts);assert saved.status_code==200,saved.text
    work=saved.json()['work_id']
    valid=request(c,'validate',{'work_id':work});assert valid.status_code==200,valid.text
    response=request(c,'submit',{'work_id':work});assert response.status_code==200,response.text
    return article,a,receipts,work,response.json()


def test_entire_authenticated_intake_stage_and_approval_flow(dashboard):
    c=dashboard
    assert c['client'].get('/api/queue').json()['approved_count']==0
    article,a,receipts,work,stage=staged(c)
    assert item(c)['stage']==stage
    assert c['client'].get('/api/queue').json()['items'][0]['state']=='staged'
    assert request(c,'submit',{'work_id':work}).json()==stage
    assert not (c['root']/'approvals').exists()
    inspected=request(c,'inspect',stage);assert inspected.status_code==200,inspected.text
    inspection=inspected.json()
    body={**stage,'inspection_token':inspection['inspection_token'],'confirm_human_review':False}
    assert request(c,'approve',body).status_code==422
    body['confirm_human_review']=True
    approved=request(c,'approve',body);assert approved.status_code==200,approved.text
    assert request(c,'approve',body).json()==approved.json()
    queue=c['client'].get('/api/queue').json()
    assert queue['approved_count']==1 and queue['eligible_count']==0
    assert queue['items'][0]['rights_status']=='unverified'
    assert len(history(c['root'])[0])==1
    assert c['client'].get('/api/candidates/'+c['candidate']+'/history').status_code==200


@pytest.mark.parametrize('attack',['csrf','origin','host','anonymous','no_inspection'])
def test_authentication_and_action_boundaries(dashboard,attack):
    c=dashboard
    if attack=='csrf':c['client'].headers['X-AIC-CSRF']='bad'
    if attack=='origin':c['client'].headers['Origin']='http://evil.example'
    if attack=='host':c['client'].headers['Host']='evil.example'
    if attack=='anonymous':c['client'].cookies.clear()
    result=request(c,'approve',{'stage_id':'stage-'+'0'*64,'confirm_human_review':True,'inspection_token':'forged'})
    assert result.status_code in (401,403)
    assert not (c['root']/'approvals').exists()


def test_pending_content_drafts_and_missing_claim_evidence(dashboard):
    c=dashboard;a=form();article=item(c)
    saved=save(c,article,a,[]);assert saved.status_code==200
    assert request(c,'validate',saved.json()).status_code==422
    article=content(c)
    # The old saved working version is an optimistic version, not an identity guess.
    bad=save(c,article,a,[],saved.json()['work_id']);assert bad.status_code==200
    result=request(c,'validate',bad.json());assert result.status_code==422
    assert 'evidence' in result.json()['error'].lower()


@pytest.mark.parametrize('change',['claim','quote','hash','actor'])
def test_evidence_receipts_bind_claim_value_quote_hash_and_actor(dashboard,change):
    c=dashboard;article=content(c);a,receipts=mapped(c,article)
    if change=='claim':a['domains']=['geopolitics']
    elif change=='quote':a['evidence'][0]['quote']='forged'
    elif change=='hash':a['evidence'][0]['content_revision_sha256']='0'*64
    else:
        c['service'].read_artifact('evidence','evidence-',receipts[0])
        actor={'id':'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','username':'other'}
        with pytest.raises(ValueError):
            c['service'].save(c['candidate'],actor,{'record_id':article['record_id'],'work_id':None,
                'annotation':a,'evidence_receipts':receipts,'supersedes':None})
        return
    assert save(c,article,a,receipts).status_code in (409,422)


def test_source_and_work_changes_invalidate_inspection(dashboard):
    c=dashboard;article,a,receipts,work,stage=staged(c)
    inspect=request(c,'inspect',stage).json()
    a['rationale']='Updated human rationale'
    updated=save(c,article,a,receipts,work);assert updated.status_code==200
    response=request(c,'approve',{**stage,'inspection_token':inspect['inspection_token'],'confirm_human_review':True})
    assert response.status_code==409
    assert not (c['root']/'approvals').exists()
    assert save(c,article,a,receipts,work).status_code==409


def test_approval_requires_explicit_amendment_and_retains_history(dashboard):
    c=dashboard;article,a,receipts,work,stage=staged(c)
    inspect=request(c,'inspect',stage).json()
    approval=request(c,'approve',{**stage,'inspection_token':inspect['inspection_token'],'confirm_human_review':True}).json()
    a['rationale']='An explicitly revised human rationale'
    assert save(c,article,a,receipts,work).status_code in (409,422)
    saved=save(c,article,a,receipts,work,approval['approval_id']);assert saved.status_code==200
    resumed=item(c)['amendment_work']
    assert resumed['annotation']==a and resumed['evidence_receipts']==receipts
    assert resumed['work_id']==saved.json()['work_id']
    second=request(c,'submit',saved.json());assert second.status_code==200,second.text
    inspect2=request(c,'inspect',second.json()).json()
    assert request(c,'approve',{**second.json(),'inspection_token':inspect2['inspection_token'],'confirm_human_review':True}).status_code==200
    assert len(history(c['root'])[0])==2


def test_source_attachment_preserves_past_work_and_invalidates_staging(dashboard):
    c=dashboard;article,a,receipts,work,stage=staged(c)
    result=request(c,'attach',{'record_id':article['record_id'],'text':'A new independently supplied source revision.',
        'content_type':'permitted_excerpt','handling_basis':'Synthetic authorized fixture'})
    assert result.status_code==200
    assert request(c,'inspect',stage).status_code==409
    assert save(c,article,a,receipts,work).status_code==409
    assert item(c)['stale_work']


def test_login_errors_docs_disabled_and_path_injection_rejected(dashboard):
    c=dashboard
    response=c['client'].post('/api/login',json={'username':'reviewer','password':'wrong'})
    assert response.status_code==401 and 'wrong' not in response.text
    assert c['client'].get('/api/docs').status_code==404
    assert c['client'].get('/api/candidates/not-a-safe-id').status_code==422
    assert c['client'].get('/api/openapi.json').status_code==404


def test_native_utf16_mapping_and_exact_quoted_source(dashboard):
    c=dashboard;article=content(c);a=form();text=article['text']
    start=text.index('\U0001f600');end=start+1
    response=request(c,'evidence',{'record_id':article['record_id'],'annotation':a,
        'start':len(text[:start].encode('utf-16-le'))//2,'end':len(text[:end].encode('utf-16-le'))//2,
        'quote':'\U0001f600','targets':['/domains/0'],'attribution':'Synthetic selected span','confirmed_mapping':True})
    assert response.status_code==200,response.text
    evidence=response.json()['mapped'][0]['evidence']
    assert evidence['start']==start and evidence['end']==end
    assert evidence['quote']==text[start:end]


def test_historical_source_text_and_existing_argilla_snapshots_are_visible(dashboard):
    from tests.test_argilla_bridge import submit
    c=dashboard
    submit({**c,'client':c['argilla_client']},status='draft')
    article=content(c)
    audit=c['client'].get('/api/candidates/'+c['candidate']+'/history').json()
    assert len(audit['argilla_responses'])==1 and audit['argilla_responses'][0]['status']=='draft'
    historical=next(r for r in audit['representations'] if not r['current'])
    result=c['client'].get('/api/candidates/'+c['candidate']+'/representations/'+historical['record_id'])
    assert result.status_code==200 and result.json()['text']=='' and not result.json()['current']
    assert c['client'].get('/api/candidates/'+c['candidate']+'/representations/record-'+'0'*64).status_code==422


def test_sync_failure_retains_source_without_inventing_approval(dashboard):
    c=dashboard
    def fail():raise RuntimeError('Simulated unavailable local service')
    c['service'].sync=fail
    article=item(c)
    result=request(c,'attach',{'record_id':article['record_id'],'text':'Synthetic source retained despite sync outage.',
        'content_type':'permitted_excerpt','handling_basis':'Synthetic handling basis'})
    assert result.status_code==200 and 'pending' in result.json()['sync_warning']
    assert item(c)['text']=='Synthetic source retained despite sync outage.'
    assert not (c['root']/'approvals').exists()


def test_session_permission_revocation_fails_closed(dashboard,monkeypatch):
    from src import review_dashboard as module
    c=dashboard
    app=module.create_app(c['service'],lambda u,p:{**ACTOR,'_token':'synthetic-token'},origin='http://testserver')
    client=TestClient(app)
    result=client.post('/api/login',headers={'Origin':'http://testserver'},json={'username':'reviewer','password':'fixture'})
    client.headers.update({'Origin':'http://testserver','X-AIC-CSRF':result.json()['csrf']})
    monkeypatch.setattr(module,'argilla_identity',lambda token:ACTOR)
    assert client.get('/api/queue').status_code==200
    def revoked(token):raise ValueError('No workspace permission')
    monkeypatch.setattr(module,'argilla_identity',revoked)
    assert client.get('/api/queue').status_code==401
    assert client.post('/api/candidates/'+c['candidate']+'/approve',json={'confirm_human_review':True}).status_code==401
    assert not (c['root']/'approvals').exists()
