"""Loopback-only FastAPI review API and locally bundled React UI."""
import argparse
import ipaddress
import os
from pathlib import Path
import secrets
import time
from uuid import UUID

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from .review_dashboard_service import ReviewService


def argilla_auth(username,password):
    """Authenticate the human directly; do not impersonate via a shared API key."""
    with httpx.Client(base_url='http://127.0.0.1:6900',trust_env=False,follow_redirects=False,timeout=10) as client:
        result=client.post('/api/v1/token',data={'username':username,'password':password})
        result.raise_for_status()
        token=result.json()['access_token']
    return {**argilla_identity(token),'_token':token}


def argilla_identity(token):
    with httpx.Client(base_url='http://127.0.0.1:6900',trust_env=False,follow_redirects=False,timeout=10) as client:
        headers={'Authorization':'Bearer '+token}
        user=client.get('/api/v1/me',headers=headers);user.raise_for_status();actor=user.json()
        if actor.get('role') not in {'owner','admin','annotator'}:raise ValueError('Reviewer role required')
        workspaces=client.get('/api/v1/me/workspaces',headers=headers);workspaces.raise_for_status()
        values=workspaces.json()
        values=values.get('items',[]) if isinstance(values,dict) else values
        if not any(w.get('name')=='aic1' for w in values):raise ValueError('Workspace permission required')
        return {'id':str(UUID(actor['id'])),'username':actor['username']}


def create_app(service=None,authenticator=None,*,origin='http://127.0.0.1:6910',static_dir=None):
    service=service or ReviewService(Path('data/argilla'),Path('data/review_dashboard'))
    authenticate=authenticator or argilla_auth
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None,debug=False)
    sessions={};attempts={}
    app.state.service=service

    @app.middleware('http')
    async def boundary(request,call_next):
        host=request.headers.get('host','')
        expected=origin.split('://',1)[1]
        try:local=ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:local=request.client.host=='testclient' and authenticator is not None
        if not local or host!=expected:
            return JSONResponse({'error':'Only the configured loopback origin is allowed'},status_code=403)
        if request.method not in {'GET','HEAD'}:
            if request.headers.get('origin')!=origin:
                return JSONResponse({'error':'Same-origin request required'},status_code=403)
            if not request.headers.get('content-type','').startswith('application/json'):
                return JSONResponse({'error':'Use application/json'},status_code=415)
            collected=bytearray()
            async for chunk in request.stream():
                collected.extend(chunk)
                if len(collected)>3*1024*1024:
                    return JSONResponse({'error':'Request exceeds 3 MiB'},status_code=413)
            request._body=bytes(collected)
        try:response=await call_next(request)
        except (ValueError,KeyError,TypeError) as exc:
            # Known validators use controlled schema messages; never expose a traceback.
            message=str(exc) if isinstance(exc,ValueError) else 'Malformed request fields. Reload and check the form.'
            response=JSONResponse({'error':message,**({'fields':exc.fields} if hasattr(exc,'fields') else {})},status_code=409 if any(w in message.lower() for w in ['stale','changed','supersed','already','reload']) else 422)
        except OSError:
            response=JSONResponse({'error':'Local review store unavailable. Check permissions and reload; no approval was inferred.'},status_code=503)
        except Exception:
            response=JSONResponse({'error':'Operation could not complete. Reload to recover the last saved version.'},status_code=500)
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Cache-Control']='no-store'
        return response

    def session(request,write=False):
        token=request.cookies.get('aic_session','')
        obj=sessions.get(token)
        if not obj or obj['expires']<time.monotonic():raise HTTPException(401,'Sign in to continue')
        if obj.get('upstream_token'):
            try:
                if argilla_identity(obj['upstream_token'])!=obj['actor']:raise ValueError()
            except Exception:raise HTTPException(401,'Reviewer access could not be verified with Argilla. Sign in again.') from None
        if write and not secrets.compare_digest(request.headers.get('x-aic-csrf',''),obj['csrf']):
            raise HTTPException(403,'Invalid action token; sign in again')
        return obj

    @app.exception_handler(HTTPException)
    async def http_error(request,exc):return JSONResponse({'error':exc.detail},status_code=exc.status_code)

    @app.post('/api/login')
    async def login(request:Request):
        moment=time.monotonic();ip=request.client.host
        tries=[t for t in attempts.get(ip,[]) if moment-t<60]
        if len(tries)>=10:raise HTTPException(429,'Too many sign-in attempts. Wait one minute.')
        attempts[ip]=tries+[moment]
        body=await request.json()
        try:
            if set(body)!={'username','password'} or not isinstance(body['username'],str) or not isinstance(body['password'],str):raise ValueError()
            authenticated=authenticate(body['username'],body['password'])
            actor={k:authenticated[k] for k in ('id','username')}
            UUID(actor['id'])
        except Exception:raise HTTPException(401,'Authentication failed or workspace access denied') from None
        token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
        for old in list(sessions):
            if sessions[old]['expires']<moment:sessions.pop(old)
        sessions[token]={'actor':actor,'csrf':csrf,'expires':moment+8*3600,'inspections':{},
                         'upstream_token':authenticated.get('_token')}
        response=JSONResponse({'actor':actor,'csrf':csrf})
        response.set_cookie('aic_session',token,httponly=True,samesite='strict',secure=False,max_age=8*3600,path='/')
        return response

    @app.get('/api/me')
    def me(request:Request):
        obj=session(request);return {'actor':obj['actor'],'csrf':obj['csrf']}

    @app.post('/api/logout')
    def logout(request:Request):
        session(request,True);sessions.pop(request.cookies.get('aic_session'),None)
        r=JSONResponse({'signed_out':True});r.delete_cookie('aic_session');return r

    @app.get('/api/queue')
    def queue(request:Request):return service.queue(session(request)['actor'])

    @app.get('/api/candidates/{candidate}')
    def candidate(candidate:str,request:Request):return service.candidate(candidate,session(request)['actor'])

    @app.get('/api/candidates/{candidate}/history')
    def audit(candidate:str,request:Request):return service.audit(candidate,session(request)['actor'])

    @app.get('/api/candidates/{candidate}/representations/{record}')
    def representation(candidate:str,record:str,request:Request):
        session(request);return service.representation(candidate,record)

    @app.post('/api/candidates/{candidate}/{action}')
    async def mutate(candidate:str,action:str,request:Request):
        obj=session(request,True);body=await request.json();actor=obj['actor']
        if action=='attach':return service.attach(candidate,actor,body)
        if action=='evidence':return service.map_evidence(candidate,actor,body)
        if action=='save':return service.save(candidate,actor,body)
        if action=='validate':return service.validate(candidate,actor,body)
        if action=='submit':return service.submit(candidate,actor,body)
        if action=='inspect':
            inspected=service.inspect(candidate,actor,body['stage_id'])
            token=secrets.token_urlsafe(32)
            obj['inspections'][token]={'stage_id':body['stage_id'],'draft_hash':inspected['draft_hash'],'expires':time.monotonic()+900}
            return {**inspected,'inspection_token':token}
        if action=='approve':
            inspection=obj['inspections'].get(body.get('inspection_token'))
            if inspection is None or inspection['expires']<time.monotonic():raise HTTPException(403,'Inspect this staged draft before approving')
            return service.approve(candidate,actor,body,inspection)
        if action=='sync':
            if service.sync is None:return {'synced':False,'message':'Argilla synchronization is not configured for this instance'}
            service.sync();return {'synced':True}
        raise HTTPException(404,'Unknown review action')

    from .research_ledger import ResearchLedger
    research=ResearchLedger(service.bridge_root,service.root/'research')

    @app.get('/api/research')
    def research_summary(request:Request):
        session(request)
        with service.lock:return research.summary()

    @app.post('/api/research/{action}')
    async def research_action(action:str,request:Request):
        actor=session(request,True)['actor'];body=await request.json()
        with service.lock:
            if action=='capture':return {'event_id':research.capture(actor,body['expected_head'],body['request_id'])}
            if action=='quality':return {'event_id':research.quality(body,actor)}
            if action=='experiment':return research.experiment(body,actor)
            if action=='preview':return research.preview(body['experiment_id'],actor,body['expected_head'],body['request_id'])
            if action=='validate-plan':return research.validate_plan(body['plan_id'])
            if action=='result':return {'event_id':research.result(body,actor)}
            if action=='export':return research.export_real(body,actor)
            raise HTTPException(404,'Unsupported research action; no training or rights endpoints exist')

    static_dir=Path(static_dir or Path(__file__).resolve().parents[1]/'dashboard/dist')
    if static_dir.exists():
        @app.get('/')
        def index():return FileResponse(static_dir/'index.html')
        app.mount('/',StaticFiles(directory=static_dir),name='ui')
    return app


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=6910)
    parser.add_argument('--bridge-root',type=Path,default=Path('data/argilla'))
    parser.add_argument('--dashboard-root',type=Path,default=Path('data/review_dashboard'))
    args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('Choose an unprivileged local port')
    os.environ['HF_HUB_DISABLE_TELEMETRY']='1';os.environ['HF_HUB_OFFLINE']='1'
    def sync():
        from .argilla_bridge import local_client,setup,import_records
        rg,client=local_client();dataset=setup(rg,client)
        return import_records(args.bridge_root,dataset,rg)
    service=ReviewService(args.bridge_root,args.dashboard_root,sync=sync)
    service.context()  # Refuse inaccessible/corrupt stores before opening a port.
    args.dashboard_root.mkdir(parents=True,exist_ok=True)
    lock=(args.dashboard_root/'writer.lock').open('a+b')
    lock.write(b'0');lock.flush();lock.seek(0)
    if os.name=='nt':
        import msvcrt
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    import uvicorn
    uvicorn.run(create_app(service,origin=f'http://127.0.0.1:{args.port}'),host='127.0.0.1',port=args.port,
                access_log=False,proxy_headers=False,workers=1)


if __name__=='__main__':main()
