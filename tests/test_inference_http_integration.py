"""Real loopback Core-client -> AIC HTTP. No production auth/data/provider calls."""
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import pytest
from tests.test_inference_service import FakeRuntime,TOKEN,payload
from src.inference_service import create_app

def test_real_core_client_to_service_and_shadow_report(tmp_path):
    import uvicorn
    core=Path(__file__).resolve().parents[2]/'argus-core'
    interpreter=core/'.venv/Scripts/python.exe'
    if not interpreter.exists():pytest.skip('Adjacent Core interpreter required for real wire-contract test')
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    app=create_app(token=TOKEN,runtime=FakeRuntime(),host=f'127.0.0.1:{port}')
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False))
    worker=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);worker.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.03)
    assert server.started
    # The production Core client runs in its own repository/interpreter, not
    # through a cross-repository Python import or shared mock HTTP transport.
    program=r'''
import sys,json,asyncio
sys.path.insert(0,'backend')
from app.clients.aic1_client import AIC1Client
from app.services.aic_shadow import ShadowJournal,record_shadow,report
args=json.loads(sys.stdin.read())
async def run():
    body=args['body']
    client=AIC1Client(args['url'],args['token'],head_sha='3'*64,revision='1'*40,encoder_sha='2'*64)
    journal=ShadowJournal(args['journal'])
    observation={'scope':'topic_relevance_v1','label':'unrelated','model':'synthetic-provider',
        'policy_sha256':'b'*64,'content_sha256':body['content_sha256'],'evidence_sha256':None}
    result=await record_shadow(client,journal,body,observation,'synthetic-application',ollama_policy='b'*64)
    assert result['status']=='succeeded',result
    assert result['result']['prediction']=='defense'
    assert result['comparison']['ollama_comparable'] is False
    assert result['comparison']['human_comparable'] is False
    assert result['operational_authority'] is False
    print(json.dumps(report(args['journal'])))
asyncio.run(run())
'''
    env=os.environ.copy();env.pop('PYTHONPATH',None);env['PYTHONDONTWRITEBYTECODE']='1'
    try:
        data={'url':f'http://127.0.0.1:{port}','token':TOKEN,'body':payload(),'journal':str(tmp_path/'wire-shadow.sqlite3')}
        result=subprocess.run([str(interpreter),'-I','-B','-c',program],cwd=core,env=env,input=json.dumps(data),text=True,capture_output=True,timeout=30)
        assert result.returncode==0,result.stderr+result.stdout
        summary=json.loads(result.stdout);assert summary['succeeded']==1 and summary['human_comparable']==0
        assert summary['empirical_deployment_accuracy'] is None
    finally:server.should_exit=True;worker.join(timeout=10);sock.close()
