"""Dashboard orchestration over authoritative Phase 2M and content services.

All working edits, evidence mappings and submissions are append-only snapshots.
The browser never supplies a filesystem path or an approval reviewer identity.
"""
from copy import deepcopy
from pathlib import Path
import threading
from uuid import UUID

from . import argilla_bridge as bridge
from .candidate_import import canonical_source
from .content_reference import check_binding
from .global_annotation_schema import ARTICLE_FIELDS, BASE_FIELDS, evidence_targets, validate_article
from .global_io import document_hash, encoded, identifier, keys, now, publish_directory, read_object, string
from .global_review import create_draft, load_draft, approve, history, eligibility_report, _family


class ReviewValidationError(ValueError):
    def __init__(self,message,fields):
        super().__init__(message);self.fields=fields


def empty_annotation():
    return {'schema_version':'aic-global-annotation-v2','domains':[],'defense_event_types':[],
            'countries':[],'organizations':[],'event_date':None,'event_location':None,
            'evidence_status':'unknown','rationale':'','event_coverage':'','event_coverage_note':'',
            'events':[],'evidence':[]}


def pointer(obj,path):
    value=obj
    for part in path.strip('/').split('/'):
        value=value[int(part)] if isinstance(value,list) else value[part]
    return value


class ReviewService:
    def __init__(self, bridge_root, dashboard_root, sync=None):
        self.bridge_root=Path(bridge_root)
        self.root=Path(dashboard_root)
        self.sync=sync
        self.lock=threading.RLock()

    def context(self,candidate=None,record=None):
        context,items,heads=bridge.records(self.bridge_root)
        if candidate is None:return context,items,heads
        identifier(candidate,'candidate-')
        if candidate not in heads:raise ValueError('Unknown queue candidate')
        if record is not None and record!=heads[candidate]:
            raise ValueError('Stale source revision. Reload the article and re-review changed text.')
        item=items[heads[candidate]]
        ref,text=(None,'') if item['source'] is None else check_binding(context['store'],item['source'])
        return context,heads[candidate],item,ref,text

    def save_artifact(self,directory,prefix,obj):
        ident=prefix+document_hash(obj)
        path=self.root/directory/ident
        if path.exists():
            if read_object(path/'data.json')!=obj:raise ValueError('Immutable dashboard artifact changed')
        else:publish_directory(path,{'data.json':encoded(obj)})
        return ident

    def read_artifact(self,directory,prefix,ident):
        identifier(ident,prefix)
        obj=read_object(self.root/directory/ident/'data.json')
        if prefix+document_hash(obj)!=ident:raise ValueError('Dashboard artifact hash mismatch')
        return obj

    def working_history(self,candidate,actor):
        result={}
        directory=self.root/'work'
        for entry in sorted(directory.iterdir()) if directory.exists() else []:
            obj=self.read_artifact('work','work-',entry.name)
            if obj['candidate_id']==candidate and obj['actor']['id']==actor['id']:result[entry.name]=obj
        if not result:return result,None
        parents=[o['parent'] for o in result.values() if o['parent'] is not None]
        if any(p not in result for p in parents) or len(set(parents))!=len(parents):
            raise ValueError('Working history is missing or forked')
        tips=set(result)-set(parents)
        if len(tips)!=1:raise ValueError('Conflicting working history')
        head=next(iter(tips));seen=set();cursor=head
        while cursor:
            if cursor in seen:raise ValueError('Working history cycle')
            seen.add(cursor);cursor=result[cursor]['parent']
        if seen!=set(result):raise ValueError('Disconnected working history')
        return result,head

    def approval_head(self,context,item):
        approvals,heads=history(context['store'])
        family=_family(canonical_source(item['candidate']['source_id']))
        return next((approvals[i] for i in heads.values()
                     if approvals[i]['annotation_id']==family),None)

    def existing_stage(self,candidate,actor,work_id):
        if work_id is None:return None
        request={'candidate_id':candidate,'work_id':work_id,'actor':actor}
        ident='stage-'+document_hash(request)
        path=self.root/'stages'/ident/'data.json'
        if not path.exists():return None
        receipt=read_object(path)
        if receipt['request']!=request:raise ValueError('Staged receipt identity mismatch')
        work=self.read_artifact('work','work-',work_id)
        draft=load_draft(self.context()[0]['store'],receipt['draft_id'])
        if draft['annotation']!=work['annotation'] or draft['source']!=work['source']:
            raise ValueError('Stored staged draft binding mismatch')
        return {'stage_id':ident,'draft_id':receipt['draft_id']}

    def queue(self,actor):
        context,items,heads=self.context()
        approvals,approval_heads=history(context['store']);eligibility=eligibility_report(context['store'])
        if not eligibility['approval_store_valid']:raise ValueError('Approval history invalid; review store must be repaired before further work')
        output=[]
        for candidate,ident in sorted(heads.items(),key=lambda pair:items[pair[1]]['candidate'].get('article_title','')):
            item=items[ident];approval=self.approval_head(context,item)
            source=item['source'];same=approval is not None and source==approval['source']
            state='approved' if same else ('pending_content' if source is None else 'content_ready')
            _,work=self.working_history(candidate,actor)
            if work and not same:state='draft'
            if work and not same and self.existing_stage(candidate,actor,work):
                saved=self.read_artifact('work','work-',work)
                if saved['record_id']==ident:state='staged'
            info=eligibility['sources'].get(source['source_ref_id'] if source else '',{})
            row=item['candidate']
            output.append({'candidate_id':candidate,'record_id':ident,'title':row['article_title'],
                'publisher':row['publisher'],'state':state,'approved':same,'eligible':bool(info.get('eligible_for_future_dataset')),
                'blockers':info.get('blocked',['missing_registered_content']),'rights_status':info.get('rights_status','unverified')})
        return {'items':output,'approved_count':len(approval_heads),'historical_approval_count':len(approvals),
                'eligible_count':eligibility['eligible_for_future_dataset'],'candidate_count':len(heads)}

    def candidate(self,candidate,actor):
        context,record,item,ref,text=self.context(candidate)
        versions,work_id=self.working_history(candidate,actor)
        approval=self.approval_head(context,item)
        annotation=empty_annotation();receipts=[];supersedes=None;stale_work=False
        if work_id:
            work=versions[work_id];stale_work=work['record_id']!=record
            annotation=deepcopy(work['annotation']);supersedes=work['supersedes']
            if stale_work:annotation['evidence']=[]
            else:receipts=work['evidence_receipts']
        current_approved=approval is not None and approval['source']==item['source']
        amendment_work=None
        if current_approved and work_id and not stale_work and versions[work_id]['supersedes']==approval['approval_id']:
            amendment_work={'work_id':work_id,**versions[work_id]}
        if current_approved:
            annotation=approval['annotation'];receipts=[]
        from .representation_policy import leakage_flags
        return {'candidate_id':candidate,'record_id':record,'metadata':item['candidate'],
            'representation_warnings':leakage_flags(text),
            'source':item['source'],'reference':ref,'text':text,'annotation':annotation,
            'evidence_receipts':receipts,'work_id':work_id,'stale_work':stale_work,
            'recoverable_work':{'work_id':work_id,**versions[work_id]} if stale_work else None,
            'amendment_work':amendment_work,
            'stage':self.existing_stage(candidate,actor,work_id) if not stale_work and not current_approved else None,
            'supersedes':supersedes,'approval':approval,'current_approved':current_approved,
            'documents':bridge.contract()['documents'],'documents_hash':document_hash(bridge.contract()['documents'])}

    def attach(self,candidate,actor,body):
        with self.lock:
            optional=set(body)&{'request_id','representation_provenance'}
            keys(body,{'record_id','text','content_type','handling_basis'}|optional,'source intake')
            request_id=body.get('request_id')
            if request_id is not None:
                UUID(request_id)
                directory=self.root/'operations'
                for entry in sorted(directory.iterdir()) if directory.exists() else []:
                    operation=self.read_artifact('operations','operation-',entry.name)
                    if operation['request_id']==request_id and operation['actor_id']==actor['id']:
                        if operation['request_sha256']!=document_hash(body) or operation['candidate_id']!=candidate:
                            raise ValueError('Attachment request identity reused with different input')
                        current=self.candidate(candidate,actor)
                        if current['record_id']!=operation['record_id']:raise ValueError('Stale attachment retry; current source has changed')
                        return {'candidate':current,'sync_warning':None,'replayed':True}
            string(body['handling_basis'],'handling basis')
            text=body['text']
            if not isinstance(text,str) or not text.strip() or len(text.encode('utf-8'))>2*1024*1024:
                raise ValueError('Supply nonempty permitted UTF-8 text, at most 2 MiB')
            context,current,item,_,_=self.context(candidate)
            origin=None
            if body['content_type']=='ai_assisted_summary':
                from .representation_policy import origin_document,ORIGIN_FIELDS
                values=body.get('representation_provenance')
                keys(values,ORIGIN_FIELDS-{'schema_version','policy_version','policy_sha256'},'AI origin declarations')
                origin=origin_document(values)
            elif body.get('representation_provenance') is not None:raise ValueError('AI origin must not be attached to a human/publisher representation')
            if body['record_id']!=current:
                # Recover an interrupted, otherwise identical attachment only.
                from .global_io import digest
                _,records,_=self.context()
                old=records.get(body['record_id'])
                ref=check_binding(context['store'],item['source'])[0] if item['source'] else None
                if (request_id is None or old is None or old['candidate']['candidate_id']!=candidate or ref is None
                    or ref['content_revision_sha256']!=digest(text.encode('utf-8'))
                    or ref['metadata']['content_type']!=body['content_type'] or ref['metadata']['rights_note']!=body['handling_basis']
                    or ref['metadata'].get('representation_provenance')!=origin):
                    raise ValueError('Stale source revision. Reload before attaching changed content.')
            # Paths are server-generated; never use a browser-provided filesystem path.
            import tempfile
            self.root.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='intake-',dir=self.root) as directory:
                path=Path(directory)/'content.utf8';path.write_bytes(text.encode('utf-8'))
                ident=bridge.attach(self.bridge_root,candidate,path,body['content_type'],body['handling_basis'],content_view=True,representation_provenance=origin)
            self.save_artifact('intake','intake-',{'candidate_id':candidate,'record_id':ident,
                'actor':actor,'at':now(),'content_type':body['content_type'],'handling_basis':body['handling_basis']})
            if request_id is not None:
                self.save_artifact('operations','operation-',{'request_id':request_id,'actor_id':actor['id'],
                    'candidate_id':candidate,'record_id':ident,'request_sha256':document_hash(body)})
            warning=None
            if self.sync:
                try:self.sync()
                except Exception:warning='Source was retained safely. Argilla metadata sync is pending; retry Sync metadata. No response or approval changed.'
            return {'candidate':self.candidate(candidate,actor),'sync_warning':warning}

    def shape(self,annotation):
        keys(annotation,ARTICLE_FIELDS,'annotation form')
        if annotation['schema_version']!='aic-global-annotation-v2':raise ValueError('Unsupported annotation schema')
        units=[annotation]+annotation['events'] if isinstance(annotation['events'],list) else []
        if not units or len(units)>101:raise ValueError('Events must be an array of at most 100 explicit instances')
        for index,unit in enumerate(units):
            if index:keys(unit,BASE_FIELDS|{'instance_id'},'event form')
            for name in ('domains','defense_event_types','countries','organizations'):
                if not isinstance(unit[name],list):raise ValueError(name+' must be an array')
        if not isinstance(annotation['evidence'],list):raise ValueError('Evidence must be an array')

    def claim_hash(self,annotation,target,source):
        if target not in evidence_targets(annotation):raise ValueError('Choose an existing supported claim target')
        return document_hash([target,pointer(annotation,target),source,bridge.contract()])

    def map_evidence(self,candidate,actor,body):
        with self.lock:
            context,record,item,ref,text=self.context(candidate,body['record_id'])
            if ref is None:raise ValueError('Attach permitted source content before selecting evidence')
            if body.get('confirmed_mapping') is not True:raise ValueError('Explicit evidence target selection is required')
            annotation=body['annotation'];self.shape(annotation)
            span=bridge.span_offsets(text,body['start'],body['end'],'utf16')
            if span['quote']!=body.get('quote'):raise ValueError('Selected quote does not match this exact source revision')
            targets=body['targets']
            if not isinstance(targets,list) or not targets or len(set(targets))!=len(targets):raise ValueError('Select one or more distinct claim targets')
            string(body['attribution'],'source attribution')
            result=[]
            for target in targets:
                evidence={'target':target,'content_revision_sha256':ref['content_revision_sha256'],
                    **{k:span[k] for k in ('start','end','quote')},'attribution':body['attribution']}
                receipt={'candidate_id':candidate,'record_id':record,'actor':actor,'source':item['source'],
                         'claim_hash':self.claim_hash(annotation,target,item['source']),'evidence':evidence}
                ident=self.save_artifact('evidence','evidence-',receipt)
                result.append({'receipt_id':ident,'evidence':evidence})
            return {'mapped':result}

    def check_evidence(self,candidate,actor,record,item,annotation,receipts):
        if not isinstance(receipts,list) or len(receipts)!=len(annotation['evidence']):
            raise ValueError('Each evidence entry needs its saved selection receipt; reselect any imported evidence')
        for ident,evidence in zip(receipts,annotation['evidence']):
            saved=self.read_artifact('evidence','evidence-',ident)
            if (saved['candidate_id']!=candidate or saved['record_id']!=record or saved['actor']['id']!=actor['id']
                or saved['source']!=item['source'] or saved['evidence']!=evidence
                or saved['claim_hash']!=self.claim_hash(annotation,evidence['target'],item['source'])):
                raise ValueError('Evidence claim or source changed. Re-select evidence for the current claims.')

    def save(self,candidate,actor,body):
        with self.lock:
            context,record,item,ref,text=self.context(candidate,body['record_id'])
            versions,head=self.working_history(candidate,actor)
            request_id=body.get('request_id')
            if request_id is not None:
                UUID(request_id);directory=self.root/'operations'
                for entry in sorted(directory.iterdir()) if directory.exists() else []:
                    operation=self.read_artifact('operations','operation-',entry.name)
                    if operation['request_id']==request_id and operation['actor_id']==actor['id']:
                        if (operation.get('kind')!='save' or operation['request_sha256']!=document_hash(body)
                            or operation['candidate_id']!=candidate):raise ValueError('Save request identity reused with different input')
                        if operation['work_id']!=head:raise ValueError('Stale save retry; a newer working version exists')
                        return {'work_id':head}
            annotation=deepcopy(body['annotation']);self.shape(annotation)
            self.check_evidence(candidate,actor,record,item,annotation,body['evidence_receipts'])
            approval=self.approval_head(context,item)
            supersedes=body.get('supersedes')
            if approval is not None and supersedes!=approval['approval_id']:
                raise ValueError('This article is approved. Explicitly start an amendment before editing.')
            if approval is None and supersedes is not None:raise ValueError('Unknown superseded approval')
            if head:
                old=versions[head]
                if all(old[k]==v for k,v in {'record_id':record,'annotation':annotation,
                    'evidence_receipts':body['evidence_receipts'],'supersedes':supersedes}.items()) and body.get('work_id')==head:
                    if request_id is not None:self.save_artifact('operations','operation-',{'kind':'save','request_id':request_id,
                        'actor_id':actor['id'],'candidate_id':candidate,'record_id':record,'work_id':head,'request_sha256':document_hash(body)})
                    return {'work_id':head}
            if body.get('work_id')!=head:raise ValueError('Stale working draft. Reload before saving; your browser edits have not been overwritten.')
            work={'candidate_id':candidate,'record_id':record,'source':item['source'],
                'documents_hash':document_hash(bridge.contract()['documents']),'actor':actor,
                'annotation':annotation,'evidence_receipts':body['evidence_receipts'],
                'supersedes':supersedes,'parent':head,'at':now()}
            work_id=self.save_artifact('work','work-',work)
            if request_id is not None:self.save_artifact('operations','operation-',{'kind':'save','request_id':request_id,
                'actor_id':actor['id'],'candidate_id':candidate,'record_id':record,'work_id':work_id,'request_sha256':document_hash(body)})
            return {'work_id':work_id}

    def validated_work(self,candidate,actor,work_id):
        work=self.read_artifact('work','work-',work_id)
        _,head=self.working_history(candidate,actor)
        if head!=work_id or work['candidate_id']!=candidate or work['actor']['id']!=actor['id']:
            raise ValueError('Stale working draft or invalid reviewer permission')
        context,record,item,ref,text=self.context(candidate,work['record_id'])
        if ref is None:raise ValueError('Attach permitted source content before validation')
        if work['source']!=item['source'] or work['documents_hash']!=document_hash(bridge.contract()['documents']):
            raise ValueError('Content or taxonomy/policy changed; review the current revision')
        self.check_evidence(candidate,actor,record,item,work['annotation'],work['evidence_receipts'])
        docs=bridge.contract()['documents']
        validate_article(work['annotation'],docs['taxonomy'],docs['policy'],text,ref['content_revision_sha256'])
        return context,item,work

    def validate(self,candidate,actor,body):
        with self.lock:
            try:self.validated_work(candidate,actor,body['work_id'])
            except ValueError as exc:
                work=self.read_artifact('work','work-',body['work_id'])
                if work['actor']['id']!=actor['id'] or work['candidate_id']!=candidate:raise
                a=work['annotation'];fields=[]
                if 'evidence' in str(exc).lower():
                    covered={e['target'] for e in a['evidence']}
                    fields=[{'path':target,'message':'Select exact registered text supporting this claim.'} for target in sorted(evidence_targets(a)-covered)]
                if not fields:
                    names=[name for name in ('domains','defense_event_types','countries','organizations','event_date','event_location','evidence_status','rationale','event_coverage_note','event_coverage') if name in str(exc)]
                    if str(exc).startswith('Defense requires'):names=['defense_event_types']
                    elif 'other is exclusive' in str(exc):names=['domains']
                    elif 'country' in str(exc).lower() or 'ISO' in str(exc):names=['countries']
                    elif any(term in str(exc) for term in ('event coverage','partial coverage','not_enumerated')):names=['event_coverage']
                    fields=[{'path':'/'+(names[0] if names else 'evidence'),'message':str(exc)}]
                raise ReviewValidationError(str(exc),fields) from exc
            return {'valid':True,'message':'Annotation and exact source evidence validated. Rights remain separate.'}

    def submit(self,candidate,actor,body):
        with self.lock:
            context,item,work=self.validated_work(candidate,actor,body['work_id'])
            request={'candidate_id':candidate,'work_id':body['work_id'],'actor':actor}
            key='stage-'+document_hash(request);path=self.root/'stages'/key
            if path.exists():
                receipt=read_object(path/'data.json')
                if receipt['request']!=request:raise ValueError('Staged receipt mismatch')
                draft=load_draft(context['store'],receipt['draft_id'])
                if draft['annotation']!=work['annotation'] or draft['source']!=item['source']:raise ValueError('Staged draft binding changed')
            else:
                ident=create_draft(context['store'],item['source']['source_ref_id'],work['annotation'],supersedes=work['supersedes'])
                receipt={'request':request,'draft_id':ident}
                publish_directory(path,{'data.json':encoded(receipt)})
            return {'stage_id':key,'draft_id':receipt['draft_id']}

    def inspect(self,candidate,actor,stage_id):
        identifier(stage_id,'stage-')
        receipt=read_object(self.root/'stages'/stage_id/'data.json')
        if stage_id!='stage-'+document_hash(receipt['request']):raise ValueError('Staged receipt hash mismatch')
        if receipt['request']['candidate_id']!=candidate or receipt['request']['actor']['id']!=actor['id']:
            raise ValueError('Invalid staged draft permission')
        context,item,work=self.validated_work(candidate,actor,receipt['request']['work_id'])
        draft=load_draft(context['store'],receipt['draft_id'])
        if draft['annotation']!=work['annotation'] or draft['source']!=item['source'] or draft['documents']!=bridge.contract()['documents']:
            raise ValueError('Staged draft or source changed')
        return {'stage_id':stage_id,'draft':draft,'draft_hash':document_hash(draft),
                'text':check_binding(context['store'],draft['source'])[1]}

    def approve(self,candidate,actor,body,inspection):
        with self.lock:
            if body.get('confirm_human_review') is not True:raise ValueError('Explicit human review confirmation is required')
            current=self.inspect(candidate,actor,body['stage_id'])
            if current['draft_hash']!=inspection['draft_hash'] or inspection['stage_id']!=body['stage_id']:
                raise ValueError('Inspection is stale; inspect the exact staged draft again')
            context=self.context()[0]
            approvals,_=history(context['store'])
            identity='argilla:'+actor['id']+':'+actor['username']
            for a in approvals.values():
                if a['draft_id']==current['draft']['draft_id']:
                    if a['reviewed_by']!=identity:raise ValueError('Draft already approved by another reviewer')
                    return {'approval_id':a['approval_id'],'approved':True}
            ident=approve(context['store'],current['draft']['draft_id'],identity,True)
            return {'approval_id':ident,'approved':True}

    def audit(self,candidate,actor):
        context,current,item,ref,text=self.context(candidate)
        _,items,heads=self.context()
        approvals,approval_heads=history(context['store'])
        versions=[{'record_id':i,'current':i==current,'source':o['source'],
                   'metadata':o['candidate']} for i,o in items.items() if o['candidate']['candidate_id']==candidate]
        approved=[{**a,'current':a['approval_id'] in approval_heads.values()} for a in approvals.values()
                  if a['annotation_id']==_family(canonical_source(item['candidate']['source_id']))]
        work,head=self.working_history(candidate,actor)
        record_ids={v['record_id'] for v in versions}
        legacy=[]
        folder=self.bridge_root/'submissions'
        for entry in sorted(folder.iterdir()) if folder.exists() else []:
            saved=bridge._read(self.bridge_root,'submissions',entry.name,'submission-')
            if saved['record_id'] in record_ids:
                legacy.append({'submission_id':entry.name,'record_id':saved['record_id'],
                    'status':saved['status'],'author':saved['reviewer_username'],'answers':saved['answers']})
        flags=[]
        folder=self.bridge_root/'quality-flags'
        for entry in sorted(folder.iterdir()) if folder.exists() else []:
            flag=read_object(entry/'advisory.json')
            if entry.name!='quality-'+document_hash(flag):raise ValueError('Quality advisory hash mismatch')
            if any(v['source']==flag['source'] for v in versions):flags.append(flag)
        return {'representations':versions,'approvals':approved,
                'working_history':[{'work_id':i,'current':i==head,**o} for i,o in work.items()],
                'argilla_responses':legacy,'quality_advisories':flags,
                'rights':eligibility_report(context['store'])['sources'].get(item['source']['source_ref_id'] if item['source'] else '',{})}

    def representation(self,candidate,record):
        context,items,heads=self.context()
        identifier(candidate,'candidate-');identifier(record,'record-')
        item=items.get(record)
        if item is None or item['candidate']['candidate_id']!=candidate:raise ValueError('Unknown article representation')
        ref,text=(None,'') if item['source'] is None else check_binding(context['store'],item['source'])
        return {'reference':ref,'text':text,'current':heads[candidate]==record}
