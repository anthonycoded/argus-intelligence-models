"""Phase 2R uses disposable approvals only; no production data or models."""
from copy import deepcopy
from uuid import uuid4
import pytest
from tests.test_argilla_bridge import bridge,attach
from tests.test_global_review import approved
from tests.test_review_dashboard import dashboard
from src.research_ledger import ResearchLedger,SYSTEM,plan_parts,synthetic_fixture,validate_fixture
from src.global_review import attest_rights,history
from src.global_io import encoded,read_object
from src.global_dataset import validate_dataset


@pytest.fixture
def ledger(bridge,tmp_path):
    attach(bridge);ident=approved(bridge)
    return bridge,ResearchLedger(bridge['bridge'],tmp_path/'research'),ident


def operation(l):return {'expected_head':l.events()[1],'request_id':str(uuid4())}


def experiment(l,ident):
    return l.experiment({**operation(l),'name':'Synthetic metadata experiment','scope':'research_only',
        'seed':42,'ratios':{'train':.7,'validation':.15,'test':.15},
        'items':[{'approval_id':ident,'include':True,'reason':'Disposable test record'}]},SYSTEM)['experiment_id']


def quality(l,ident,**overrides):
    body={**operation(l),'approval_id':ident,'status':'accepted','observations':'Synthetic fixture inspected',
        'event_group_ids':['event-fixture'],'duplicate_group_ids':[],'regions':['Africa'],'language':'en','confirm_quality_review':True}
    body.update(overrides)
    return l.quality(body,SYSTEM)


def test_live_contract_and_independent_gates(ledger):
    c,l,ident=ledger;s=l.summary()
    assert s['approved_count']==1 and s['rights_eligible_count']==0
    assert s['domains']=={'defense':1} and s['representation_types']=={'human_summary':1}
    assert s['evidenced_country_roles']=={'BR/participant':1,'KE/host':1}
    assert not s['readiness']['dataset_ready']
    assert s['rows'][0]['covered_evidence_targets']==s['rows'][0]['required_evidence_targets']
    quality(l,ident)
    assert l.summary()['quality_accepted_count']==1 and l.summary()['fully_eligible_count']==0
    assert len(history(c['root'])[0])==1 and not (c['root']/'rights').exists()


def test_append_version_idempotency_stale_head_and_tamper(ledger):
    c,l,ident=ledger;op=operation(l)
    event=l.capture(SYSTEM,**op)
    assert l.capture(SYSTEM,**op)==event
    assert len(l.events()[0])==1
    with pytest.raises(ValueError,match='Stale'):l.capture(SYSTEM,None,str(uuid4()))
    quality(l,ident);quality(l,ident,status='excluded',observations='Later synthetic observation')
    assert len(l.events()[0])==3 and l.summary()['rows'][0]['quality_status']=='excluded'
    path=l.root/'events'/event/'event.json';obj=read_object(path);obj['payload']['rows']=[];path.write_bytes(encoded(obj))
    with pytest.raises(ValueError,match='hash'):l.events()


@pytest.mark.parametrize('field,value',[('confirm_quality_review',False),('status','cleared'),('regions',['invented']),('language','English'),('observations','')])
def test_quality_validation(ledger,field,value):
    _,l,ident=ledger
    with pytest.raises(ValueError):quality(l,ident,**{field:value})
    assert not l.events()[0]


def test_preview_reproducibility_idempotency_and_stale_quality(ledger):
    _,l,ident=ledger;exp=experiment(l,ident);op=operation(l)
    first=l.preview(exp,SYSTEM,**op);second=l.preview(exp,SYSTEM,**op)
    assert first==second and first['training_export'] is False
    assert 'rights_unverified' in first['readiness']['blockers']
    assert 'text' not in first['rows'][0]
    assert l.validate_plan(first['plan_id'])['partitions']==first['partitions']
    quality(l,ident)
    with pytest.raises(ValueError,match='Stale'):l.validate_plan(first['plan_id'])


def test_rehashed_plan_configuration_tampering(ledger):
    _,l,ident=ledger;exp=experiment(l,ident);plan=l.preview(exp,SYSTEM,**operation(l))
    obj=l.read_artifact('plans','plan-',plan['plan_id']);obj['seed']=43
    ident=l.artifact('plans','plan-',obj)
    with pytest.raises(ValueError,match='configuration'):l.validate_plan(ident)


@pytest.mark.parametrize('status',['unverified','restricted'])
def test_research_only_cannot_export_uncleared_rights(ledger,status):
    c,l,ident=ledger
    if status=='restricted':attest_rights(c['root'],c['source'],status,'Synthetic restricted decision','fixture-reviewer',True)
    quality(l,ident);exp=experiment(l,ident)
    with pytest.raises(ValueError,match='rights'):l.export_real({**operation(l),'experiment_id':exp,'confirm_group_review':True},SYSTEM)
    assert not (l.root/'exports').exists()


def test_real_export_uses_existing_validator_and_quality_gate(ledger):
    c,l,ident=ledger;attest_rights(c['root'],c['source'],'cleared','Synthetic fixture owned by test author','fixture-reviewer',True)
    exp=experiment(l,ident)
    with pytest.raises(ValueError,match='quality'):l.export_real({**operation(l),'experiment_id':exp,'confirm_group_review':True},SYSTEM)
    quality(l,ident);exp=experiment(l,ident);op=operation(l)
    out=l.export_real({**op,'experiment_id':exp,'confirm_group_review':True},SYSTEM)
    assert l.export_real({**op,'experiment_id':exp,'confirm_group_review':True},SYSTEM)==out
    manifest=validate_dataset(l.root/'exports'/out['export_id'])
    assert manifest['readiness']['snapshot_eligible'] is True
    assert manifest['readiness']['supervised_split_ready'] is False
    assert manifest['readiness']['training_supported'] is False


def test_stale_write_creates_no_export_or_experiment(ledger):
    _,l,ident=ledger;l.capture(SYSTEM,**operation(l))
    with pytest.raises(ValueError,match='Stale'):l.experiment({'expected_head':None,'request_id':str(uuid4()),'name':'x','scope':'research_only','seed':42,'ratios':{},'items':[]},SYSTEM)
    assert not (l.root/'experiments').exists()


def test_changed_source_fails_closed(ledger):
    c,l,_=ledger
    paths=list((c['root']/'sources'/c['source']).glob('*'))
    text=next(p for p in paths if p.name=='content.utf8');text.write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError):l.summary()


def test_grouped_deterministic_planning():
    rows=[]
    for i in range(60):
        rows.append({'approval_id':str(i),'source_ref_id':str(i),'canonical_source_id':str(i),
            'content_revision_sha256':str(i),'duplicate_fingerprint':str(i),
            'event_group_ids':[str(i//2)],'duplicate_group_ids':[], 'task_label':'defense' if i%2 else 'nondefense'})
    ratios={'train':.7,'validation':.15,'test':.15}
    result=plan_parts(rows,42,ratios)
    assert result==plan_parts(rows,42,ratios) and result!=plan_parts(rows,43,ratios)
    assert all(result.values())
    owners={i:s for s,ids in result.items() for i in ids}
    assert all(owners[str(i)]==owners[str(i+1)] for i in range(0,60,2))
    rows[2]['duplicate_group_ids']=['same'];rows[4]['duplicate_group_ids']=['same']
    result=plan_parts(rows,42,ratios);owners={i:s for s,ids in result.items() for i in ids}
    assert owners['2']==owners['4']==owners['5']


@pytest.mark.parametrize('ratios',[{'train':1},dict(train=.8,validation=.2,test=.2),dict(train=True,validation=0,test=0)])
def test_invalid_ratios(ratios):
    with pytest.raises(ValueError):plan_parts([],42,ratios)


def test_synthetic_fixture_isolated_reproducible_and_no_overwrite(tmp_path):
    a,b=tmp_path/'a',tmp_path/'b'
    assert synthetic_fixture(a)==synthetic_fixture(b)
    assert validate_fixture(a)=={'valid':True,'synthetic_records':60,'training_executed':False}
    with pytest.raises((ValueError,FileExistsError)):synthetic_fixture(a)
    with pytest.raises((ValueError,FileNotFoundError,KeyError)):validate_dataset(a)
    obj=read_object(a/'manifest.json');obj['partitions']['test'].append(obj['partitions']['train'][0]);(a/'manifest.json').write_bytes(encoded(obj))
    with pytest.raises(ValueError,match='leakage'):validate_fixture(a)


def test_research_dashboard_auth_and_csrf(dashboard):
    c=dashboard;client=c['client']
    response=client.get('/api/research');assert response.status_code==200,response.text
    assert response.json()['approved_count']==0
    body={'expected_head':None,'request_id':str(uuid4())}
    assert client.post('/api/research/capture',json=body,headers={'X-AIC-CSRF':'invalid'}).status_code==403
    assert client.post('/api/research/capture',json=body,headers={'Origin':'http://evil.test'}).status_code==403
    assert client.post('/api/research/capture',json=body).status_code==200
    assert client.post('/api/research/train',json={}).status_code==404
    client.cookies.clear();assert client.get('/api/research').status_code==401


def test_no_unapproved_labels_and_no_fabricated_results(ledger):
    _,l,ident=ledger;exp=experiment(l,ident);p=l.preview(exp,SYSTEM,**operation(l))
    with pytest.raises(ValueError):l.result({**operation(l),'plan_id':p['plan_id'],'metrics':{'accuracy':float('nan')},'notes':'Fixture'},SYSTEM)
    event=l.result({**operation(l),'plan_id':p['plan_id'],'metrics':{'fixture_metric':.5},'notes':'Manually supplied synthetic result, no model run'},SYSTEM)
    assert l.events()[0][-1][1]['payload']['results_origin']=='user_supplied_not_verified_by_AIC1'


def test_missing_provenance_blocks_even_metadata_preview(ledger):
    c,l,_=ledger
    (c['root']/'sources'/c['source']/'provenance.json').unlink()
    with pytest.raises((ValueError,OSError)):l.inventory()


def test_rights_change_invalidates_frozen_preview(ledger):
    c,l,ident=ledger;exp=experiment(l,ident);p=l.preview(exp,SYSTEM,**operation(l))
    attest_rights(c['root'],c['source'],'restricted','Synthetic fixture restriction','fixture-reviewer',True)
    with pytest.raises(ValueError,match='Stale'):l.validate_plan(p['plan_id'])
    assert l.summary()['rights_eligible_count']==0


def test_conflicting_rights_are_not_eligible(ledger):
    c,l,ident=ledger;attest_rights(c['root'],c['source'],'cleared','Synthetic fixture owned','fixture-reviewer',True)
    attest_rights(c['root'],c['source'],'restricted','Contradictory synthetic decision','fixture-reviewer',True)
    assert l.summary()['rows'][0]['rights_status']=='conflicting_decisions'
    exp=experiment(l,ident)
    with pytest.raises(ValueError,match='rights'):l.export_real({**operation(l),'experiment_id':exp,'confirm_group_review':True},SYSTEM)


def test_forged_partition_and_unknown_approval_rejected(ledger):
    _,l,ident=ledger;exp=experiment(l,ident);p=l.preview(exp,SYSTEM,**operation(l))
    obj=l.read_artifact('plans','plan-',p['plan_id']);obj['partitions']['test']=[ident]
    bad=l.artifact('plans','plan-',obj)
    with pytest.raises(ValueError,match='reproducibility'):l.validate_plan(bad)
    with pytest.raises(ValueError,match='Missing/current'):quality(l,'approval-'+'f'*64)


def test_unknown_geography_never_becomes_fully_eligible(ledger):
    c,l,ident=ledger;attest_rights(c['root'],c['source'],'cleared','Synthetic fixture owned','fixture-reviewer',True)
    quality(l,ident,regions=['unknown'])
    assert not l.summary()['rows'][0]['fully_eligible']


def test_related_hints_share_groups_without_changing_labels(ledger,monkeypatch):
    c,l,ident=ledger
    from src import research_ledger as module
    approvals,heads=history(c['root']);other=deepcopy(approvals[ident]);other_id='approval-'+'e'*64
    # Disposable history injection isolates deterministic duplicate hinting.
    approvals[other_id]=other;heads['synthetic-second']=other_id
    path=c['root']/'approvals'/other_id;path.mkdir();(path/'approval.json').write_bytes(encoded(other))
    monkeypatch.setattr(module,'history',lambda root:(approvals,heads))
    rows=l.inventory()['rows']
    assert len(rows)==2 and rows[0]['domains']==rows[1]['domains']==['defense']
    assert set(rows[0]['duplicate_group_ids'])&set(rows[1]['duplicate_group_ids'])
    with pytest.raises(ValueError,match='Duplicate record'):
        plan_parts(rows,42,{'train':.7,'validation':.15,'test':.15})
    # Distinct source identities with related content must stay together too.
    rows[1]['source_ref_id']='src-'+'d'*64
    parts=plan_parts(rows,42,{'train':.7,'validation':.15,'test':.15})
    assert sum(bool(ids) for ids in parts.values())==1


def test_cross_process_writer_lock_is_fail_closed(ledger):
    _,l,_=ledger
    from src.research_ledger import ledger_writer
    with ledger_writer(l.root):
        with pytest.raises(ValueError,match='busy'):l.capture(SYSTEM,**operation(l))


def test_rehashed_readiness_cannot_claim_training_ready(ledger):
    _,l,ident=ledger;exp=experiment(l,ident);p=l.preview(exp,SYSTEM,**operation(l))
    obj=l.read_artifact('plans','plan-',p['plan_id']);obj['readiness']['training_ready']=True
    forged=l.artifact('plans','plan-',obj)
    with pytest.raises(ValueError,match='readiness'):l.validate_plan(forged)


def test_research_dashboard_quality_and_preview_routes(dashboard):
    c=dashboard;attach(c);ident=approved(c);client=c['client']
    def op():return {'expected_head':client.get('/api/research').json()['ledger_head'],'request_id':str(uuid4())}
    body={**op(),'approval_id':ident,'status':'accepted','observations':'Disposable authenticated quality review',
        'event_group_ids':['fixture-event'],'duplicate_group_ids':[],'regions':['Africa'],'language':'en','confirm_quality_review':False}
    assert client.post('/api/research/quality',json=body).status_code==422
    body['confirm_quality_review']=True
    assert client.post('/api/research/quality',json=body).status_code==200
    data=client.get('/api/research').json();assert data['quality_accepted_count']==1 and data['rights_eligible_count']==0
    assert data['label_coverage']['domains']['cybersecurity']==0
    exp=client.post('/api/research/experiment',json={**op(),'name':'Fixture GUI preview','scope':'research_only',
        'seed':42,'ratios':{'train':.7,'validation':.15,'test':.15},'items':[{'approval_id':ident,'include':True,'reason':'Fixture route validation'}]})
    assert exp.status_code==200,exp.text
    plan=client.post('/api/research/preview',json={**op(),'experiment_id':exp.json()['experiment_id']})
    assert plan.status_code==200,plan.text
    assert client.post('/api/research/validate-plan',json={'plan_id':plan.json()['plan_id']}).status_code==200
    result=client.post('/api/research/export',json={**op(),'experiment_id':exp.json()['experiment_id'],'confirm_group_review':True})
    assert result.status_code==422 and 'rights' in result.json()['error']
    assert len(history(c['root'])[0])==1 and not (c['root']/'rights').exists()
