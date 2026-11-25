"""Independent loopback-only experimental inference. Never starts the dashboard."""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import hmac
import ipaddress
import os
from pathlib import Path
import time
from uuid import uuid4
from fastapi import FastAPI,HTTPException,Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from .global_io import parse_json
from .inference_contracts import ContentInput,RetrievalInput,Classification
from .inference_audit import Audit
from .inference_runtime import Runtime

MAX_BODY=128*1024

def create_app(*,token,runtime=None,loader=None,index=None,index_loader=None,audit=None,host='127.0.0.1:6920',deadline=5.):
    if not isinstance(token,str) or not 32<=len(token)<=256 or token.strip()!=token:raise ValueError('Dedicated 32-256 character service token required')
    if not 0<deadline<=30:raise ValueError('Inference deadline must be bounded to 30 seconds')
    executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='aic-inference')

    @asynccontextmanager
    async def lifespan(app):
        app.state.runtime=runtime;app.state.index=index;app.state.busy=False
        try:
            if app.state.runtime is None and loader is not None:
                try:app.state.runtime=await asyncio.get_running_loop().run_in_executor(executor,loader)
                except Exception:app.state.runtime=None
            if app.state.runtime is not None and index_loader is not None:
                try:app.state.index=index_loader(app.state.runtime)
                except Exception:app.state.index=None
            yield
        finally:executor.shutdown(wait=True,cancel_futures=True)

    app=FastAPI(title='AIC-1 experimental inference',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)

    @app.middleware('http')
    async def boundary(request,call_next):
        peer=request.client.host
        try:local=ipaddress.ip_address(peer).is_loopback
        except ValueError:local=peer=='testclient' and runtime is not None
        if not local or request.headers.get('host')!=host or request.headers.get('origin') or request.url.query:
            return JSONResponse({'error':'Service-to-service loopback access only'},403)
        if request.url.path!='/health/live':
            supplied=request.headers.get('x-api-key','')
            if len(supplied)>256 or not hmac.compare_digest(supplied.encode(),token.encode()):return JSONResponse({'error':'Unauthorized'},401)
        if request.method=='POST':
            if not request.headers.get('content-type','').startswith('application/json'):return JSONResponse({'error':'JSON required'},415)
            body=bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body)>MAX_BODY:return JSONResponse({'error':'Request too large'},413)
            try:parse_json(body.decode('utf-8'))
            except (ValueError,UnicodeError):return JSONResponse({'error':'Malformed JSON'},422)
            request._body=bytes(body)
        try:response=await call_next(request)
        except Exception:return JSONResponse({'error':'Experimental service unavailable'},503)
        response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request,error):return JSONResponse({'error':'Invalid request contract','fields':[{'loc':e['loc'],'type':e['type']} for e in error.errors()]},422)

    @app.get('/health/live')
    def live():return {'schema_version':'aic-experimental-v1','experimental':True,'live':True}

    @app.get('/health/ready')
    def ready():
        rt=app.state.runtime
        if rt is None:raise HTTPException(503,'Pinned model unavailable')
        return {'ready':True,'experimental':True,'encoder':rt.identity,'classifier_sha256':rt.head_sha256,'retrieval_ready':app.state.index is not None}

    async def operate(body,kind):
        rt=app.state.runtime
        if rt is None:raise HTTPException(503,'Pinned model unavailable')
        if app.state.busy:raise HTTPException(429,'Inference capacity busy',headers={'Retry-After':'1'})
        app.state.busy=True;start=time.perf_counter()
        def work():
            source=None;human={'status':'unavailable'};text=body.text
            if body.source_ref_id is not None:
                if app.state.index is None:raise ValueError('No registered-content permission index')
                text,source=app.state.index.resolve(body.source_ref_id,body.content_sha256)
                human=app.state.index.human_reference(source)
            if kind=='classify':
                score=float(rt.classify(text));threshold=rt.head['threshold']
                result=Classification(request_id=body.request_id,article_id=body.article_id,content_sha256=body.content_sha256,
                    classifier_sha256=rt.head_sha256,source_artifact_sha256=rt.head['source_artifact_sha256'],encoder=rt.identity,
                    defense_score=score,threshold=threshold,prediction='defense' if score>=threshold else 'nondefense',
                    training_origin=rt.head['training_origin'],human_reference=human,
                    execution={'id':uuid4(),'duration_ms':(time.perf_counter()-start)*1000}).model_dump(mode='json')
            elif kind=='embeddings':
                result={'schema_version':'aic-experimental-v1','experimental':True,'request_id':str(body.request_id),
                    'content_sha256':body.content_sha256,'encoder':rt.identity,'dimension':384,'vector':rt.embed(text).tolist()}
            else:
                if app.state.index is None:raise ValueError('No permitted index configured')
                result={'schema_version':'aic-experimental-v1','experimental':True,'request_id':str(body.request_id),
                    'content_sha256':body.content_sha256,'index_sha256':body.index_sha256,'encoder':rt.identity,
                    'similarity_is_confidence':False,'results':app.state.index.search(text,body.index_sha256,body.top_k)}
            if audit is not None:audit.append({'request_id':str(body.request_id),'article_id':body.article_id,'operation':kind,
                'content_sha256':body.content_sha256,'classifier_sha256':rt.head_sha256,'encoder':rt.identity,
                'status':'succeeded','duration_ms':(time.perf_counter()-start)*1000})
            return result
        future=asyncio.get_running_loop().run_in_executor(executor,work)
        def completed(done):
            if not done.cancelled():done.exception()  # Consume late errors without logging content.
            app.state.busy=False
        future.add_done_callback(completed)
        try:return await asyncio.wait_for(asyncio.shield(future),deadline)
        except asyncio.TimeoutError:raise HTTPException(504,'Experimental inference deadline exceeded') from None
        except (ValueError,OSError,KeyError,TypeError):raise HTTPException(503,'Model, index, permission or audit state unavailable') from None

    @app.post('/v1/classify')
    async def classify(body:ContentInput):return await operate(body,'classify')

    @app.post('/v1/embeddings')
    async def embeddings(body:ContentInput):return await operate(body,'embeddings')

    @app.post('/v1/retrieve')
    async def retrieve(body:RetrievalInput):return await operate(body,'retrieve')
    return app

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=6920)
    parser.add_argument('--head',type=Path,required=True);parser.add_argument('--head-sha256',required=True)
    parser.add_argument('--encoder',type=Path,required=True);parser.add_argument('--revision',required=True)
    parser.add_argument('--state-root',type=Path,default=Path('data/inference'));parser.add_argument('--index',type=Path)
    parser.add_argument('--index-sha256');parser.add_argument('--store',type=Path,default=Path('data/global_annotations'))
    parser.add_argument('--allow-synthetic-fixtures',action='store_true');args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('Unprivileged loopback port required')
    args.state_root.mkdir(parents=True,exist_ok=True)
    lock=(args.state_root/'service.lock').open('a+b');lock.write(b'0');lock.flush();lock.seek(0)
    if os.name=='nt':
        import msvcrt
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    def load_index(rt):
        if args.index is None:return None
        from .inference_retrieval import RetrievalIndex
        return RetrievalIndex(args.index,args.index_sha256,args.store,rt,allow_fixture=args.allow_synthetic_fixtures)
    app=create_app(token=os.environ.get('AIC_INFERENCE_TOKEN',''),host=f'127.0.0.1:{args.port}',
        loader=lambda:Runtime(args.head,args.head_sha256,args.encoder,args.revision),index_loader=load_index,
        audit=Audit(args.state_root/'requests.sqlite3'))
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=args.port,workers=1,access_log=False,proxy_headers=False,limit_concurrency=8,timeout_keep_alive=5)

if __name__=='__main__':main()
