"""Offline contracts; all content, heads and permissions here are disposable."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from uuid import uuid4
import numpy as np
import pytest
from fastapi.testclient import TestClient
from src.global_io import encoded,read_object,now
from src.inference_contracts import ContentInput,Classification,text_hash
from src.inference_service import create_app
from src.inference_runtime import Runtime,encoder_identity,convert_trusted_head,file_hash
from src.inference_audit import Audit
from src.inference_retrieval import build_index,RetrievalIndex

TOKEN='PUBLIC-DISPOSABLE-SERVICE-TEST-TOKEN-ONLY'
REV='1'*40
IDENTITY={'name':'sentence-transformers/all-MiniLM-L6-v2','revision':REV,'directory_sha256':'2'*64,'dimension':384,'max_sequence_length':256,'normalized':True}

class FakeRuntime:
    identity=IDENTITY;head_sha256='3'*64
    head={'threshold':.5,'source_artifact_sha256':'4'*64,'training_origin':'synthetic_fixture'}
    def embed(self,text):return np.array([1.]+[0.]*383)
    def classify(self,text):return .75

def payload(text='A fictional fleet tested naval equipment.'):
    return {'request_id':str(uuid4()),'article_id':'disposable-article','text':text,'content_sha256':text_hash(text),
        'authorized_for_processing':True,'handling_basis':'Explicit synthetic fixture for software testing only'}

def client(rt=None,**kwargs):
    app=create_app(token=TOKEN,runtime=rt or FakeRuntime(),host='testserver',**kwargs)
    c=TestClient(app);c.headers['X-API-Key']=TOKEN
    return c

def test_authenticated_classification_digest_and_authority(tmp_path):
    audit=Audit(tmp_path/'audit.sqlite3');body=payload()
    with client(audit=audit) as c:
        response=c.post('/v1/classify',json=body);assert response.status_code==200,response.text
        result=Classification.model_validate_json(response.content)
        assert result.defense_score==.75 and result.prediction=='defense' and not result.probability_calibrated
        assert result.content_sha256==body['content_sha256'] and result.human_reference.status=='unavailable'
        assert c.get('/health/ready').status_code==200
    record=audit.read()[0]
    assert body['text'] not in json.dumps(record) and TOKEN not in json.dumps(record)

@pytest.mark.parametrize('kind',['missing','wrong','origin','host'])
def test_service_auth_and_origin_boundaries(kind):
    with client() as c:
        headers={}
        if kind=='missing':c.headers.pop('X-API-Key')
        if kind=='wrong':headers['X-API-Key']='wrong'
        if kind=='origin':headers['Origin']='http://evil.example'
        if kind=='host':headers['Host']='evil.example'
        assert c.post('/v1/classify',json=payload(),headers=headers).status_code in {401,403}

@pytest.mark.parametrize('change',[{'content_sha256':'0'*64},{'authorized_for_processing':False},{'authorized_for_processing':1},
    {'text':''},{'text':'x'*16001},{'extra_endpoint':'http://169.254.169.254'}])
def test_invalid_inputs_fail_before_inference(change):
    rt=FakeRuntime();rt.classify=lambda text:pytest.fail('Inference must not run')
    with client(rt) as c:
        result=c.post('/v1/classify',json={**payload(),**change});assert result.status_code==422
        assert 'PUBLIC-DISPOSABLE' not in result.text

def test_body_size_duplicate_json_and_missing_model():
    with client() as c:
        assert c.post('/v1/classify',content=b'x'*(128*1024+1),headers={'Content-Type':'application/json'}).status_code==413
        assert c.post('/v1/classify',content='{"text":"x","text":"y"}',headers={'Content-Type':'application/json'}).status_code==422
        c.app.state.runtime=None
        assert c.get('/health/ready').status_code==503
        assert c.post('/v1/classify',json=payload()).status_code==503

def test_timeout_retains_concurrency_slot_until_work_really_finishes():
    rt=FakeRuntime();started=threading.Event();finish=threading.Event()
    def blocked(text):started.set();finish.wait(2);return .75
    rt.classify=blocked
    with client(rt,deadline=.02) as c:
        assert c.post('/v1/classify',json=payload()).status_code==504
        assert started.is_set()
        assert c.post('/v1/classify',json=payload()).status_code==429
        finish.set()
        for _ in range(50):
            if not c.app.state.busy:break
            time.sleep(.01)
        rt.classify=lambda text:.75
        assert c.post('/v1/classify',json=payload()).status_code==200

def test_embedding_and_unconfigured_retrieval():
    with client() as c:
        result=c.post('/v1/embeddings',json=payload()).json();assert len(result['vector'])==384
        assert c.post('/v1/retrieve',json={**payload(),'index_sha256':'0'*64}).status_code==503

def test_audit_restart_tamper_and_append_only(tmp_path):
    path=tmp_path/'audit.db';a=Audit(path);a.append({'status':'fixture'});b=Audit(path)
    assert len(b.read())==1;b.append({'status':'second'});assert len(Audit(path).read())==2
    with sqlite3.connect(path) as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE events SET payload=\'{}\'')
        db.execute('DROP TRIGGER no_event_update');db.execute('UPDATE events SET payload=\'{}\' WHERE n=1')
    with pytest.raises((ValueError,KeyError)):Audit(path)

def test_no_pickle_before_explicit_trust_and_digest(tmp_path,monkeypatch):
    import builtins
    original=builtins.__import__
    def guard(name,*args,**kwargs):
        if name in {'joblib','torch','sentence_transformers'}:pytest.fail('No model/pickle imports before validation')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',guard)
    with pytest.raises(ValueError,match='confirmation'):convert_trusted_head(tmp_path/'head.joblib','a'*64,tmp_path,REV,tmp_path/'out')
    bad=tmp_path/'bad.json';bad.write_text('{}')
    with pytest.raises(ValueError):Runtime(bad,'0'*64,tmp_path,REV)

def test_pinned_numeric_head_and_encoder(tmp_path):
    directory=tmp_path/REV;directory.mkdir();(directory/'1_Pooling').mkdir()
    for name in ('model.safetensors','config.json','tokenizer.json','1_Pooling/config.json'):(directory/name).write_text('{}')
    (directory/'config.json').write_text('{"model_type":"bert","hidden_size":384}')
    (directory/'sentence_bert_config.json').write_text('{"max_seq_length":256}')
    (directory/'modules.json').write_text('[{"type":"sentence_transformers.models.Transformer","path":""}]')
    identity=encoder_identity(directory,REV)
    head={'schema_version':'aic-numeric-defense-v1','encoder':identity,'coefficients':[0.]*384,'intercept':0.,'classes':[0,1],
        'threshold':.5,'training_origin':'synthetic_fixture','source_artifact_sha256':'4'*64,'packages':{},'dataset_sha256':'5'*64,'split_sha256':'6'*64}
    path=tmp_path/'head.json';path.write_bytes(encoded(head))
    class FakeEncoder:
        def encode(self,*args,**kwargs):return np.array([[1.]+[0.]*383])
    rt=Runtime(path,file_hash(path),directory,REV,encoder_factory=FakeEncoder)
    assert rt.classify('fixture')==.5
    (directory/'tokenizer.json').write_text('{"changed":true}')
    with pytest.raises(ValueError,match='identity'):Runtime(path,file_hash(path),directory,REV,encoder_factory=FakeEncoder)

def permission(c):
    from src.content_reference import load_source
    binding=load_source(c['root'],c['source'])[2]
    return {'schema_version':'aic-processing-permission-v1','source':binding,'scope':'local_inference_and_retrieval','permitted':True,
        'reviewed_by':'synthetic-fixture-author','reviewed_at':now(),'handling_basis':'Disposable fixture only, no production clearance','synthetic_fixture':True}

def test_frozen_retrieval_source_grounding_and_synthetic_segregation(global_case,tmp_path):
    c=global_case;rt=FakeRuntime();p=permission(c);out=tmp_path/'index'
    sha=build_index(c['root'],[p],out,rt,version='fixture-v1',allow_fixture=True)
    with pytest.raises(ValueError):RetrievalIndex(out/'index.json',sha,c['root'],rt)
    index=RetrievalIndex(out/'index.json',sha,c['root'],rt,allow_fixture=True)
    rows=index.search('fixture',sha,5);assert rows[0]['synthetic_fixture'] is True
    assert rows[0]['source']['content_revision_sha256']==p['source']['content_revision_sha256']
    assert rows[0]['excerpt']==c['text'][:600]
    with pytest.raises(ValueError,match='revision'):index.search('fixture','0'*64,5)
    with pytest.raises(FileExistsError):build_index(c['root'],[p],out,rt,version='fixture-v1',allow_fixture=True)
    (c['root']/'sources'/c['source']/'content.utf8').write_text('stale')
    with pytest.raises(ValueError):index.search('fixture',sha,5)

def test_retrieval_rights_restriction_and_missing_permission(global_case,tmp_path):
    from src.global_review import attest_rights
    c=global_case;p=permission(c);p['permitted']=False
    with pytest.raises(ValueError):build_index(c['root'],[p],tmp_path/'bad',FakeRuntime(),version='v1',allow_fixture=True)
    p['permitted']=True;attest_rights(c['root'],c['source'],'restricted','Synthetic restriction','fixture-reviewer',True)
    with pytest.raises(ValueError,match='rights'):build_index(c['root'],[p],tmp_path/'bad',FakeRuntime(),version='v1',allow_fixture=True)
