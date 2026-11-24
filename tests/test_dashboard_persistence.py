"""Persistence/AI origin regressions on disposable data. No approval actions."""
from copy import deepcopy
from uuid import uuid4
import pytest
from tests.test_argilla_bridge import bridge
from tests.test_review_dashboard import dashboard,content,form,item,mapped,request,save
from src.content_reference import load_source,register_source
from src.global_io import digest,encoded,read_object
from src.global_review import rights_status
from src.representation_policy import origin_document


def test_partial_evidence_validation_is_read_only_and_actionable(dashboard):
    c=dashboard;article=content(c);a,receipts=mapped(c,article)
    a['domains'].append('geopolitics')
    saved=save(c,article,a,receipts);assert saved.status_code==200
    work=saved.json()['work_id'];path=c['service'].root/'work'/work/'data.json';before=path.read_bytes()
    for _ in range(2):
        result=request(c,'validate',{'work_id':work});assert result.status_code==422,result.text
        assert result.json()['fields']==[{'path':'/domains/1','message':'Select exact registered text supporting this claim.'}]
        assert path.read_bytes()==before
        current=item(c);assert current['annotation']==a and current['evidence_receipts']==receipts
    assert not (c['root']/'approvals').exists()


def test_content_change_recovers_fields_without_reusing_evidence(dashboard):
    c=dashboard;article=content(c);a,receipts=mapped(c,article)
    saved=save(c,article,a,receipts).json();original=(c['service'].root/'work'/saved['work_id']/'data.json').read_bytes()
    attached=request(c,'attach',{'record_id':article['record_id'],'text':'Replacement synthetic registered revision.',
        'content_type':'human_summary','handling_basis':'Synthetic source rights unverified','request_id':str(uuid4())})
    assert attached.status_code==200,attached.text
    new=attached.json()['candidate'];assert new['annotation']['domains']==a['domains']
    assert new['annotation']['rationale']==a['rationale']
    assert new['annotation']['evidence']==[] and new['evidence_receipts']==[]
    assert new['recoverable_work']['annotation']==a
    assert (c['service'].root/'work'/saved['work_id']/'data.json').read_bytes()==original
    assert request(c,'save',{'record_id':new['record_id'],'annotation':a,'evidence_receipts':receipts,'work_id':saved['work_id'],'supersedes':None}).status_code==409


def test_save_request_retry_and_stale_response_cannot_overwrite_new_work(dashboard):
    c=dashboard;article=content(c);a,receipts=mapped(c,article)
    body={'record_id':article['record_id'],'work_id':None,'annotation':a,'evidence_receipts':receipts,'supersedes':None,'request_id':str(uuid4())}
    first=request(c,'save',body);assert first.status_code==200
    assert request(c,'save',body).json()==first.json()
    updated=deepcopy(a);updated['rationale']='A newer independently entered fixture rationale'
    newer=save(c,article,updated,receipts,first.json()['work_id']);assert newer.status_code==200
    assert request(c,'save',body).status_code==409
    assert item(c)['annotation']['rationale']==updated['rationale']
    altered={**body,'annotation':updated};assert request(c,'save',altered).status_code==422
    assert len(c['service'].working_history(c['candidate'],{'id':'12345678-1234-4234-8234-123456789abc'})[0])==2


def test_attach_retry_does_not_make_extra_revisions(dashboard):
    c=dashboard;before=item(c)
    body={'record_id':before['record_id'],'text':'Synthetic retry representation.', 'content_type':'human_summary',
        'handling_basis':'Synthetic fixture','request_id':str(uuid4())}
    first=request(c,'attach',body);assert first.status_code==200
    second=request(c,'attach',body);assert second.status_code==200 and second.json()['replayed']
    assert second.json()['candidate']['record_id']==first.json()['candidate']['record_id']
    assert request(c,'attach',{**body,'text':'Different input for the same UUID.'}).status_code==422


def declarations(url,**values):
    return {'generation_method':'ai_generated','source_reference':url,'model_provider':None,'model_name':None,
        'human_editing_status':'unedited','human_review_status':'not_reviewed','original_content_revision_sha256':None,**values}


def test_ai_representation_origin_is_versioned_and_rights_independent(dashboard):
    c=dashboard;before=item(c);values=declarations(before['metadata']['source_id'])
    body={'record_id':before['record_id'],'text':'Synthetic AI-assisted fixture, not publisher text or verified facts.',
        'content_type':'ai_assisted_summary','handling_basis':'Test-author supplied synthetic AI provenance fixture; original source rights unverified','representation_provenance':values}
    result=request(c,'attach',body);assert result.status_code==200,result.text
    after=result.json()['candidate'];ref,text,binding=load_source(c['root'],after['source']['source_ref_id'])
    assert ref['schema_version']=='aic-content-reference-v2'
    assert ref['metadata']['representation_provenance']==origin_document(values)
    assert ref['content_revision_sha256']==digest(body['text'].encode())
    assert rights_status(c['root'],ref['source_ref_id'])=='unverified'
    assert not (c['root']/'approvals').exists() and not (c['root']/'rights').exists()


@pytest.mark.parametrize('bad',[{'source_reference':'https://other.example/report'},{'human_review_status':'approved'},
    {'model_name':''},{'generation_method':'ai_generated_human_edited'},{'original_content_revision_sha256':'0'*64}])
def test_ai_bad_or_missing_origin_rejected(dashboard,bad):
    c=dashboard;before=item(c);body={'record_id':before['record_id'],'text':'Synthetic AI test representation.',
        'content_type':'ai_assisted_summary','handling_basis':'Synthetic handling','representation_provenance':declarations(before['metadata']['source_id'],**bad)}
    result=request(c,'attach',body);assert result.status_code in (422,503),result.text
    assert item(c)['record_id']==before['record_id']


def test_ai_original_revision_binds_existing_content_and_cannot_relabel_history(dashboard):
    c=dashboard;old=content(c);source_dir=c['root']/'sources'/old['source']['source_ref_id']
    protected={p.name:p.read_bytes() for p in source_dir.iterdir()}
    values=declarations(old['metadata']['source_id'],generation_method='ai_generated_human_edited',human_editing_status='edited',human_review_status='reviewed',original_content_revision_sha256=old['source']['content_revision_sha256'])
    result=request(c,'attach',{'record_id':old['record_id'],'text':'A distinct synthetic AI-assisted edited representation.', 'content_type':'ai_assisted_summary','handling_basis':'Synthetic handling, no rights clearance','representation_provenance':values})
    assert result.status_code==200,result.text
    assert all((source_dir/name).read_bytes()==raw for name,raw in protected.items())
    assert load_source(c['root'],old['source']['source_ref_id'])[0]['metadata']['content_type']=='human_summary'


def test_ai_type_without_declarations_fails_closed(dashboard):
    c=dashboard;before=item(c)
    result=request(c,'attach',{'record_id':before['record_id'],'text':'Synthetic AI content.', 'content_type':'ai_assisted_summary','handling_basis':'Synthetic basis'})
    assert result.status_code==422


def test_ai_leakage_advisories_do_not_create_labels():
    from src.representation_policy import leakage_flags
    assert leakage_flags('Expected label: defense; domain: economics; classified as military technology')
    assert leakage_flags('A fleet evaluated sensors and discussed economic investment.')==[]


@pytest.mark.parametrize('change',['origin','policy','schema'])
def test_ai_provenance_tampering_rejected(dashboard,change):
    c=dashboard;before=item(c)
    response=request(c,'attach',{'record_id':before['record_id'],'text':'Synthetic immutable AI representation.',
        'content_type':'ai_assisted_summary','handling_basis':'Synthetic handling only',
        'representation_provenance':declarations(before['metadata']['source_id'])})
    assert response.status_code==200,response.text
    source=response.json()['candidate']['source']['source_ref_id'];path=c['root']/'sources'/source/'reference.json'
    obj=read_object(path)
    if change=='origin':obj['metadata']['representation_provenance']['model_name']='changed'
    elif change=='policy':obj['metadata']['representation_provenance']['policy_sha256']='0'*64
    else:obj['schema_version']='aic-content-reference-v1'
    path.write_bytes(encoded(obj))
    with pytest.raises(ValueError):load_source(c['root'],source)


def test_concurrent_distinct_saves_cannot_fork_or_overwrite(dashboard):
    from concurrent.futures import ThreadPoolExecutor
    c=dashboard;article=content(c);a,receipts=mapped(c,article)
    def attempt(index):
        annotation={**a,'rationale':f'Distinct concurrent fixture edit {index}'}
        return request(c,'save',{'record_id':article['record_id'],'work_id':None,'annotation':annotation,
            'evidence_receipts':receipts,'supersedes':None,'request_id':str(uuid4())})
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,range(2)))
    assert sorted(r.status_code for r in results)==[200,409]
    successful=next(i for i,r in enumerate(results) if r.status_code==200)
    assert item(c)['annotation']['rationale']==f'Distinct concurrent fixture edit {successful}'


def test_old_attachment_retry_never_restores_superseded_content(dashboard):
    c=dashboard;before=item(c);body={'record_id':before['record_id'],'text':'Original synthetic attachment.',
        'content_type':'human_summary','handling_basis':'Synthetic basis','request_id':str(uuid4())}
    first=request(c,'attach',body);assert first.status_code==200
    new={**body,'record_id':first.json()['candidate']['record_id'],'text':'Latest synthetic attachment.', 'request_id':str(uuid4())}
    assert request(c,'attach',new).status_code==200
    assert request(c,'attach',body).status_code==409
    assert item(c)['text']==new['text']
