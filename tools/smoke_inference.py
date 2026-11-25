"""Explicit local-only, real-encoder Core HTTP smoke using disposable synthetic text.

Starts no persistent service, contacts no provider, creates no human approvals.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_reference import register_source,load_source
from src.global_io import encoded,now
from src.inference_runtime import Runtime,file_hash
from src.inference_retrieval import build_index,RetrievalIndex
from src.inference_service import create_app
from src.inference_audit import Audit

CORE_PROGRAM = r'''
import sys,json,asyncio
sys.path.insert(0,'backend')
from app.clients.aic1_client import AIC1Client
from app.services.aic_shadow import ShadowJournal,record_shadow,record_retrieval,report
args=json.loads(sys.stdin.read())
async def run():
    client=AIC1Client(args['url'],args['token'],head_sha=args['head'],revision=args['encoder']['revision'],
        encoder_sha=args['encoder']['directory_sha256'],index_sha=args['index'],allow_synthetic=True,timeout=10)
    journal=ShadowJournal(args['journal'])
    observation={'scope':'topic_relevance_v1','label':'unrelated','model':'synthetic-observation',
        'policy_sha256':'b'*64,'content_sha256':args['raw']['content_sha256'],'evidence_sha256':None}
    rows=[]
    for body in (args['raw'],args['reference']):
        row=await record_shadow(client,journal,body,observation,'disposable-software-smoke',ollama_policy='b'*64)
        assert row['status']=='succeeded',row
        assert row['comparison']['ollama_comparable'] is False and row['comparison']['human_comparable'] is False
        rows.append(row)
    retrieval=await record_retrieval(client,journal,{**args['raw'],'index_sha256':args['index'],'top_k':1},'disposable-software-smoke')
    assert retrieval['status']=='succeeded',retrieval
    assert retrieval['result']['results'][0]['synthetic_fixture'] is True
    assert retrieval['result']['results'][0]['source']['source_ref_id']==args['reference']['source_ref_id']
    print(json.dumps({'classification_results':rows,'retrieval_source_count':len(retrieval['result']['results']),
        'retrieval_index_sha256':retrieval['result']['index_sha256'],'report':report(args['journal'])}))
asyncio.run(run())
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--head',type=Path,required=True);p.add_argument('--head-sha256',required=True)
    p.add_argument('--encoder',type=Path,required=True);p.add_argument('--revision',required=True)
    p.add_argument('--core',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('Choose a new disposable smoke directory')
    rt=Runtime(a.head,a.head_sha256,a.encoder,a.revision)
    a.output.mkdir(parents=True)
    text='Synthetic software fixture: a navy evaluated a fictional radar sensor. No actual event is asserted.'
    source_text=a.output/'fixture.txt';source_text.write_bytes(text.encode())
    store=a.output/'fixture-store'
    metadata={'source_id':'https://example.org/aic-software-fixture','publisher':'Synthetic fixture publisher',
        'adapter':'manual','article_title':'Synthetic software smoke only','published_at':None,'published_at_raw':None,
        'collected_at':now(),'content_type':'other_permitted','rights_note':'Original synthetic software test text only',
        'provenance_method':'synthetic_test_fixture'}
    source=register_source(store,metadata,source_text);binding=load_source(store,source)[2]
    permission={'schema_version':'aic-processing-permission-v1','source':binding,'scope':'local_inference_and_retrieval',
        'permitted':True,'reviewed_by':'software-fixture-owner','reviewed_at':now(),
        'handling_basis':'Original disposable software fixture, no real source clearance','synthetic_fixture':True}
    index_sha=build_index(store,[permission],a.output/'fixture-index',rt,version='synthetic-smoke-v1',allow_fixture=True)
    index=RetrievalIndex(a.output/'fixture-index/index.json',index_sha,store,rt,allow_fixture=True)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    token=secrets.token_urlsafe(32)
    app=create_app(token=token,runtime=rt,index=index,audit=Audit(a.output/'service.sqlite3'),host=f'127.0.0.1:{port}',deadline=10)
    import uvicorn
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    try:
        for _ in range(200):
            if server.started:break
            time.sleep(.05)
        if not server.started:raise RuntimeError('Disposable server failed to start')
        body={'request_id':str(uuid4()),'article_id':'disposable-software-smoke','text':text,'source_ref_id':None,
            'content_sha256':hashlib.sha256(text.encode()).hexdigest(),'authorized_for_processing':True,
            'handling_basis':'Original disposable software fixture'}
        reference={**body,'request_id':str(uuid4()),'text':None,'source_ref_id':source}
        arguments={'url':f'http://127.0.0.1:{port}','token':token,'head':rt.head_sha256,'encoder':rt.identity,
            'index':index_sha,'journal':str((a.output/'core-shadow.sqlite3').resolve()),'raw':body,'reference':reference}
        env=os.environ.copy();env.pop('PYTHONPATH',None);env['PYTHONDONTWRITEBYTECODE']='1'
        process=subprocess.run([str(a.core/'.venv/Scripts/python.exe'),'-I','-B','-c',CORE_PROGRAM],cwd=a.core,
            env=env,input=json.dumps(arguments),text=True,capture_output=True,timeout=45)
        if process.returncode:raise RuntimeError('Core smoke failed: '+process.stderr[-2000:])
        report=json.loads(process.stdout)
        (a.output/'smoke-report.json').write_bytes(encoded(report))
        print(json.dumps({'head_sha256':rt.head_sha256,'encoder':rt.identity,'report':report['report'],
            'retrieval_source_count':report['retrieval_source_count'],'output':str(a.output)}))
    finally:server.should_exit=True;thread.join(15);sock.close()


if __name__=='__main__':main()
