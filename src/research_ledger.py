"""Auditable research inventory, quality decisions and metadata-only split plans.

research_only is a workflow scope, never a rights decision. No model imports,
training entry point, automatic human approvals or rights changes are implemented.
"""
import argparse
from contextlib import contextmanager
import os
from collections import Counter
import math
from pathlib import Path
import random
import re
from uuid import UUID, uuid4

from . import argilla_bridge as bridge
from .content_reference import load_source
from .global_annotation_schema import evidence_targets
from .global_dataset import components, validate_partitions, split_rows, export_dataset, validate_dataset
from .global_feeds import REGIONS
from .global_io import digest, document_hash, encoded, identifier, keys, now, publish_directory, read_object, string
from .global_review import history, rights_status

SPLITS=('train','validation','test')
ALGORITHM='aic-research-group-split-v1'
SYSTEM={'id':'system:inventory','username':'technical inventory capture'}
KINDS={'inventory','quality','experiment','plan','result','export'}


def unique_strings(value,name):
    if not isinstance(value,list) or any(not isinstance(v,str) or not v.strip() for v in value) or len(set(value))!=len(value):
        raise ValueError(name+' requires distinct nonempty strings')


def plan_parts(rows,seed,ratios):
    if type(seed) is not int:raise ValueError('An explicit integer seed is required')
    keys(ratios,set(SPLITS),'split ratios')
    if any(type(v) not in (float,int) or not math.isfinite(v) or v<=0 for v in ratios.values()) or not math.isclose(sum(ratios.values()),1):
        raise ValueError('Split ratios must be positive finite numbers summing to one')
    groups=components(rows);random.Random(seed).shuffle(groups);groups.sort(key=len,reverse=True)
    parts={name:[] for name in SPLITS}
    totals=Counter(r['task_label'] for r in rows)
    for group in groups:
        counts=Counter(r['task_label'] for r in group)
        def cost(name):
            existing=Counter(r['task_label'] for r in parts[name])
            return sum(((existing[k]+counts[k]-totals[k]*ratios[name])**2-(existing[k]-totals[k]*ratios[name])**2)/max(totals[k]*ratios[name],1) for k in totals)
        choice=min(SPLITS,key=cost);parts[choice].extend(group)
    for name in parts:parts[name].sort(key=lambda r:r['approval_id'])
    validate_partitions(parts)
    return {name:[r['approval_id'] for r in parts[name]] for name in SPLITS}


@contextmanager
def ledger_writer(root):
    """Serialize append publication across dashboard and inventory CLI processes."""
    root.mkdir(parents=True,exist_ok=True)
    with (root/'writer.lock').open('a+b') as stream:
        if stream.seek(0,2)==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('Research ledger is busy; refresh and retry') from exc
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


class ResearchLedger:
    def __init__(self,bridge_root,root):
        self.bridge_root=Path(bridge_root);self.root=Path(root)

    def events(self):
        events={};ops=set();directory=self.root/'events'
        for entry in sorted(directory.iterdir()) if directory.exists() else []:
            identifier(entry.name,'event-');obj=read_object(entry/'event.json')
            keys(obj,{'schema_version','index','parent','kind','actor','at','request_id','payload'},'research event')
            if obj['schema_version']!='aic-research-ledger-v1' or entry.name!='event-'+document_hash(obj) or obj['kind'] not in KINDS:
                raise ValueError('Research ledger hash/schema mismatch')
            UUID(obj['request_id'])
            if obj['request_id'] in ops:raise ValueError('Repeated ledger operation identity')
            ops.add(obj['request_id']);events[entry.name]=obj
        ordered=sorted(events.items(),key=lambda pair:pair[1]['index']);previous=None
        for index,(ident,obj) in enumerate(ordered,1):
            if type(obj['index']) is not int or obj['index']!=index or obj['parent']!=previous:
                raise ValueError('Missing, forked or reordered research ledger history')
            previous=ident
        return ordered,previous

    def append(self,kind,payload,actor,expected_head,request_id):
        with ledger_writer(self.root):
            if kind not in KINDS:raise ValueError('Unknown research event kind')
            UUID(request_id);keys(actor,{'id','username'},'ledger actor');string(actor['id'],'actor');string(actor['username'],'actor name')
            events,head=self.events()
            for ident,event in events:
                if event['request_id']==request_id:
                    if event['kind']!=kind or event['payload']!=payload or event['actor']!=actor:
                        raise ValueError('Ledger request identity reused with different data')
                    return ident
            if expected_head!=head:raise ValueError('Stale ledger head. Refresh Dataset Quality before writing.')
            obj={'schema_version':'aic-research-ledger-v1','index':len(events)+1,'parent':head,'kind':kind,
                 'actor':actor,'at':now(),'request_id':request_id,'payload':payload}
            ident='event-'+document_hash(obj)
            publish_directory(self.root/'events'/ident,{'event.json':encoded(obj)})
            return ident

    def artifact(self,folder,prefix,obj,filename='manifest.json'):
        ident=prefix+document_hash(obj);target=self.root/folder/ident
        if target.exists():
            if read_object(target/filename)!=obj:raise ValueError('Immutable research artifact differs')
        else:publish_directory(target,{filename:encoded(obj)})
        return ident

    def check_write(self,expected_head,request_id):
        UUID(request_id)
        events,head=self.events()
        if expected_head!=head and not any(e['request_id']==request_id for _,e in events):
            raise ValueError('Stale ledger head. Refresh Dataset Quality before writing.')

    def read_artifact(self,folder,prefix,ident):
        identifier(ident,prefix);obj=read_object(self.root/folder/ident/'manifest.json')
        if ident!=prefix+document_hash(obj):raise ValueError('Research artifact hash mismatch')
        return obj

    def inventory(self):
        context,records,record_heads=bridge.records(self.bridge_root)
        approvals,heads=history(context['store']);events,ledger_head=self.events()
        quality={e['payload']['approval_id']:(ident,e['payload']) for ident,e in events if e['kind']=='quality'}
        flags=[];directory=self.bridge_root/'quality-flags'
        for entry in sorted(directory.iterdir()) if directory.exists() else []:
            obj=read_object(entry/'advisory.json')
            if entry.name!='quality-'+document_hash(obj):raise ValueError('Quality advisory hash mismatch')
            flags.append(obj)
        rows=[];texts={}
        for approval_id in sorted(heads.values()):
            approval=approvals[approval_id];ref,text,binding=load_source(context['store'],approval['source']['source_ref_id'])
            if binding!=approval['source']:raise ValueError('Stale approval content/provenance binding')
            matched=[r for r in records.values() if r['source']==binding]
            metadata=matched[0]['candidate'] if matched else {}
            current=any(records[i]['source']==binding for i in record_heads.values())
            status=rights_status(context['store'],ref['source_ref_id'])
            if status not in {'unverified','cleared','restricted','conflicting_decisions'}:raise ValueError('Invalid rights status')
            rights_dir=Path(context['store'])/'rights'/ref['source_ref_id']
            rights_hashes={p.parent.name:digest(p.read_bytes()) for p in sorted(rights_dir.glob('*/decision.json'))} if rights_dir.exists() else {}
            review_id,review=quality.get(approval_id,(None,None))
            if review and (review['source']!=binding or review['approval_sha256']!=digest((Path(context['store'])/'approvals'/approval_id/'approval.json').read_bytes())):
                raise ValueError('Stale quality review binding')
            observations=[]
            for flag in flags:
                if flag['source']==binding:observations.append({'kind':'stored_advisory','risk':flag['risk']})
            from .representation_policy import leakage_flags
            observations.extend(leakage_flags(text))
            if ref['metadata']['content_type']=='ai_assisted_summary':
                observations.append({'kind':'ai_assisted_representation','risk':'Independently review source grounding and human editing declarations'})
            blockers=[]
            if not current:blockers.append('approved_representation_is_not_current_in_review_queue')
            if status!='cleared':blockers.append('rights_'+status)
            if not review or review['status']!='accepted':blockers.append('quality_not_accepted')
            if not review or not review['event_group_ids'] or not review['regions'] or 'unknown' in review['regions'] or review['language']=='unknown':
                blockers.append('human_grouping_region_or_language_review_missing')
            ann=approval['annotation']
            row={'approval_id':approval_id,'approval_sha256':digest((Path(context['store'])/'approvals'/approval_id/'approval.json').read_bytes()),
                'representation_record_ids':sorted(i for i,r in records.items() if r['source']==binding),
                'source_ref_id':ref['source_ref_id'],'source_binding':binding,'canonical_source_id':ref['canonical_source_id'],
                'content_revision_sha256':ref['content_revision_sha256'],'duplicate_fingerprint':ref['duplicate_fingerprint'],
                'article_title':ref['metadata']['article_title'],'publisher':ref['metadata']['publisher'],
                'content_type':ref['metadata']['content_type'],'domains':ann['domains'],'defense_event_types':ann['defense_event_types'],
                'task_label':'defense' if 'defense' in ann['domains'] else 'nondefense',
                'taxonomy_sha256':approval['taxonomy_sha256'],'annotation_policy_sha256':approval['annotation_policy_sha256'],
                'rights_status':status,'rights_evidence_sha256':rights_hashes,'representation_current':current,
                'quality_status':review['status'] if review else 'unreviewed','quality_event_id':review_id,
                'observations':review['observations'] if review else '',
                'event_group_ids':review['event_group_ids'] if review else [],'duplicate_group_ids':review['duplicate_group_ids'] if review else [],
                'regions':review['regions'] if review else [],'language':review['language'] if review else 'unknown',
                'evidenced_countries':ann['countries'],'publisher_origin_region':metadata.get('source_region'),
                'publisher_country':metadata.get('publisher_country'),'declared_language':metadata.get('language'),
                'evidence_entries':len(ann['evidence']),'required_evidence_targets':len(evidence_targets(ann)),
                'covered_evidence_targets':len({e['target'] for e in ann['evidence']}),
                'quality_flags':observations,'inclusion_blockers':blockers,'fully_eligible':not blockers}
            rows.append(row);texts[approval_id]=text
        # Conservative, deterministic related-content hints; never classification labels.
        shingles={}
        truncated=False
        for ident,text in texts.items():
            tokens=re.findall(r'\w+',text.casefold());truncated|=len(tokens)>5000
            tokens=tokens[:5000];shingles[ident]={tuple(tokens[i:i+5]) for i in range(max(0,len(tokens)-4))}
        related=[]
        for i,left in enumerate(rows):
            for right in rows[i+1:]:
                a,b=shingles[left['approval_id']],shingles[right['approval_id']]
                exact=left['duplicate_fingerprint']==right['duplicate_fingerprint'] or left['canonical_source_id']==right['canonical_source_id']
                score=len(a&b)/len(a|b) if a and b else 0
                if exact or score>=.8:
                    group='related-'+document_hash(sorted([left['approval_id'],right['approval_id']]))
                    for row in (left,right):row['duplicate_group_ids']=sorted(set(row['duplicate_group_ids']+[group]))
                    related.append({'approval_ids':[left['approval_id'],right['approval_id']],
                                    'basis':'exact_identity' if exact else 'five_token_jaccard_v1','similarity':score})
        return {'schema_version':'aic-research-inventory-v1','rows':rows,'inventory_sha256':document_hash(rows),
                'ledger_head':ledger_head,'related_groups':related,'near_duplicate_scan_truncated':truncated}

    def summary(self):
        inv=self.inventory();rows=inv['rows']
        taxonomy=bridge.records(self.bridge_root)[0]['contract']['documents']['taxonomy']
        def counts(name):return dict(sorted(Counter(v for r in rows for v in r[name]).items()))
        blockers=[]
        if len(rows)<30:blockers.append('Fewer than 30 approved records; existing supervised split criterion is unmet')
        if any(r['rights_status']!='cleared' for r in rows):blockers.append('Training rights remain uncleared for one or more records')
        if any(r['quality_status']!='accepted' for r in rows):blockers.append('Quality acceptance is incomplete')
        if any(r['inclusion_blockers'] for r in rows):blockers.append('Resolve per-record source, rights, quality and grouping blockers')
        try:split_rows(rows,42)
        except ValueError as exc:blockers.append(str(exc))
        experiments=[];plans=[]
        for _,event in self.events()[0]:
            if event['kind']=='experiment':
                ident=event['payload']['experiment_id'];config=self.read_artifact('experiments','experiment-',ident)
                if not any(e['experiment_id']==ident for e in experiments):
                    experiments.append({'experiment_id':ident,**{k:config[k] for k in ('name','seed','ratios','items')},
                        'current':config['inventory_sha256']==inv['inventory_sha256']})
            if event['kind']=='plan':
                ident=event['payload']['plan_id'];manifest=self.read_artifact('plans','plan-',ident)
                if not any(p['plan_id']==ident for p in plans):
                    plans.append({'plan_id':ident,'experiment_id':manifest['experiment_id'],
                        'current':manifest['inventory_sha256']==inv['inventory_sha256']})
        return {**inv,'approved_count':len(rows),'rights_eligible_count':sum(r['rights_status']=='cleared' and r['representation_current'] for r in rows),
            'quality_accepted_count':sum(r['quality_status']=='accepted' for r in rows),'fully_eligible_count':sum(r['fully_eligible'] for r in rows),
            'domains':counts('domains'),'defense_event_types':counts('defense_event_types'),
            'label_coverage':{name:{label:sum(label in row[name] for row in rows) for label in taxonomy[name]}
                              for name in ('domains','defense_event_types')},
            'class_balance':dict(Counter(r['task_label'] for r in rows)),
            'publishers':dict(Counter(r['publisher'] for r in rows)),
            'representation_types':dict(Counter(r['content_type'] for r in rows)),
            'evidenced_country_roles':dict(Counter(c['code']+'/'+c['role'] for r in rows for c in r['evidenced_countries'])),
            'human_reviewed_regions':counts('regions'),
            'publisher_origin_regions':dict(Counter(r['publisher_origin_region'] or 'unknown' for r in rows)),
            'readiness':{'dataset_ready':bool(rows) and not blockers,'training_executed':False,
                         'training_entrypoint_implemented':False,'blockers':list(dict.fromkeys(blockers))},
            'region_vocabulary':sorted(REGIONS),
            'experiments':experiments,'plans':plans,
            'ledger_events':[{'event_id':i,**e} for i,e in self.events()[0]]}

    def capture(self,actor,expected_head,request_id):
        inventory=self.inventory();inventory.pop('ledger_head')
        return self.append('inventory',inventory,actor,expected_head,request_id)

    def quality(self,body,actor):
        required={'approval_id','status','observations','event_group_ids','duplicate_group_ids','regions','language',
                  'confirm_quality_review','expected_head','request_id'}
        keys(body,required,'quality decision')
        if body['confirm_quality_review'] is not True:raise ValueError('Explicit quality review confirmation required; this does not clear rights')
        if body['status'] not in {'accepted','needs_review','excluded'}:raise ValueError('Unsupported quality status')
        string(body['observations'],'reviewer quality observations')
        for field in ('event_group_ids','duplicate_group_ids','regions'):unique_strings(body[field],field)
        if not set(body['regions'])<=set(REGIONS):raise ValueError('Unknown reviewed region')
        if not isinstance(body['language'],str) or not re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]+)*|unknown',body['language']):raise ValueError('Invalid reviewed language')
        row=next((r for r in self.inventory()['rows'] if r['approval_id']==body['approval_id']),None)
        if row is None:raise ValueError('Missing/current human approval required for quality review')
        payload={k:body[k] for k in ('approval_id','status','observations','event_group_ids','duplicate_group_ids','regions','language')}
        payload.update(source=row['source_binding'],approval_sha256=row['approval_sha256'])
        return self.append('quality',payload,actor,body['expected_head'],body['request_id'])

    def experiment(self,body,actor):
        keys(body,{'name','seed','ratios','scope','items','expected_head','request_id'},'experiment configuration')
        self.check_write(body['expected_head'],body['request_id'])
        if body['scope']!='research_only':raise ValueError('Only research_only experiment preparation is supported; it is not rights clearance')
        string(body['name'],'experiment name')
        inv=self.inventory();rows={r['approval_id']:r for r in inv['rows']}
        if not isinstance(body['items'],list) or not body['items']:raise ValueError('Explicit inclusion/exclusion decisions required')
        seen=set()
        for item in body['items']:
            keys(item,{'approval_id','include','reason'},'experiment item')
            if item['approval_id'] not in rows or item['approval_id'] in seen:raise ValueError('Unknown, stale or duplicate experiment approval')
            seen.add(item['approval_id'])
            if type(item['include']) is not bool:raise ValueError('Explicit inclusion choice required')
            string(item['reason'],'inclusion/exclusion reason')
        if seen!=set(rows):raise ValueError('Record explicit inclusion/exclusion reasons for every current approval')
        selected=[rows[i['approval_id']] for i in body['items'] if i['include']]
        if not selected:raise ValueError('Select at least one approved record for metadata-only preview')
        plan_parts(selected,body['seed'],body['ratios'])
        config={k:body[k] for k in ('name','seed','ratios','scope','items')}
        config.update(schema_version='aic-research-experiment-v1',inventory_sha256=inv['inventory_sha256'],inventory_rows=inv['rows'])
        ident=self.artifact('experiments','experiment-',config)
        event=self.append('experiment',{'experiment_id':ident,'config_sha256':document_hash(config)},actor,body['expected_head'],body['request_id'])
        return {'experiment_id':ident,'event_id':event}

    def preview(self,experiment_id,actor,expected_head,request_id):
        self.check_write(expected_head,request_id)
        config=self.read_artifact('experiments','experiment-',experiment_id)
        inv=self.inventory()
        if config['inventory_sha256']!=inv['inventory_sha256']:raise ValueError('Stale experiment inventory; save a refreshed configuration')
        selected_ids={i['approval_id'] for i in config['items'] if i['include']}
        selected=[r for r in inv['rows'] if r['approval_id'] in selected_ids]
        support=[]
        try:split_rows(selected,config['seed'])
        except ValueError as exc:support.append(str(exc))
        manifest={'schema_version':'aic-research-split-plan-v1','algorithm':ALGORITHM,'scope':'research_only',
            'training_export':False,'experiment_id':experiment_id,'inventory_sha256':inv['inventory_sha256'],
            'seed':config['seed'],'ratios':config['ratios'],'rows':selected,
            'partitions':plan_parts(selected,config['seed'],config['ratios']),
            'readiness':{'training_ready':False,'rights_eligible_selected':sum(r['rights_status']=='cleared' for r in selected),
                         'blockers':sorted({b for r in selected for b in r['inclusion_blockers']})+support}}
        ident=self.artifact('plans','plan-',manifest)
        self.append('plan',{'plan_id':ident,'snapshot_sha256':document_hash(manifest)},actor,expected_head,request_id)
        return {'plan_id':ident,**manifest}

    def validate_plan(self,plan_id):
        manifest=self.read_artifact('plans','plan-',plan_id)
        keys(manifest,{'schema_version','algorithm','scope','training_export','experiment_id','inventory_sha256','seed','ratios','rows','partitions','readiness'},'research plan')
        if manifest['schema_version']!='aic-research-split-plan-v1' or manifest['algorithm']!=ALGORITHM or manifest['training_export'] is not False:
            raise ValueError('Unsupported research plan; not a training export')
        inv=self.inventory()
        if manifest['inventory_sha256']!=inv['inventory_sha256']:raise ValueError('Stale research snapshot')
        if manifest['partitions']!=plan_parts(manifest['rows'],manifest['seed'],manifest['ratios']):raise ValueError('Split plan reproducibility/leakage mismatch')
        config=self.read_artifact('experiments','experiment-',manifest['experiment_id'])
        if config['scope']!='research_only' or config['inventory_rows']!=inv['rows']:
            raise ValueError('Frozen configuration differs from validated human-approved inventory')
        if any(manifest[k]!=config[k] for k in ('seed','ratios','scope','inventory_sha256')):
            raise ValueError('Plan configuration differs from frozen experiment')
        chosen={i['approval_id'] for i in config['items'] if i['include']}
        expected=[r for r in config['inventory_rows'] if r['approval_id'] in chosen]
        if manifest['rows']!=expected:raise ValueError('Snapshot membership differs from frozen experiment')
        support=[]
        try:split_rows(expected,config['seed'])
        except ValueError as exc:support.append(str(exc))
        readiness={'training_ready':False,'rights_eligible_selected':sum(r['rights_status']=='cleared' for r in expected),
            'blockers':sorted({b for r in expected for b in r['inclusion_blockers']})+support}
        if manifest['readiness']!=readiness:raise ValueError('Research readiness differs from current eligibility and split support')
        if not any(e['kind']=='plan' and e['payload']=={'plan_id':plan_id,'snapshot_sha256':document_hash(manifest)} for _,e in self.events()[0]):
            raise ValueError('Research plan has no matching ledger publication')
        return manifest

    def result(self,body,actor):
        keys(body,{'plan_id','metrics','notes','expected_head','request_id'},'experiment result')
        self.validate_plan(body['plan_id']);string(body['notes'],'result notes')
        if not isinstance(body['metrics'],dict) or any(not isinstance(k,str) or type(v) not in (int,float) or not math.isfinite(v) for k,v in body['metrics'].items()):
            raise ValueError('Results must be explicit finite numeric metrics; no results are generated automatically')
        return self.append('result',{'plan_id':body['plan_id'],'metrics':body['metrics'],'notes':body['notes'],
            'results_origin':'user_supplied_not_verified_by_AIC1'},actor,body['expected_head'],body['request_id'])

    def export_real(self,body,actor):
        keys(body,{'experiment_id','confirm_group_review','expected_head','request_id'},'real export request')
        self.check_write(body['expected_head'],body['request_id'])
        if body['confirm_group_review'] is not True:raise ValueError('Explicit cohort grouping review confirmation required')
        config=self.read_artifact('experiments','experiment-',body['experiment_id'])
        if config['ratios']!={'train':.7,'validation':.15,'test':.15}:
            raise ValueError('Protected real exporter supports only 70/15/15; other ratios are metadata previews only')
        inv=self.inventory()
        if config['inventory_sha256']!=inv['inventory_sha256']:raise ValueError('Stale experiment inventory')
        chosen={i['approval_id'] for i in config['items'] if i['include']};rows=[r for r in inv['rows'] if r['approval_id'] in chosen]
        if not rows or any(r['rights_status']!='cleared' for r in rows):raise ValueError('Real export blocked: every source needs independent cleared training rights')
        if any(r['inclusion_blockers'] for r in rows):raise ValueError('Real export blocked: accept quality and review current sources, grouping, regions and language')
        cohort={'schema_version':'aic-global-cohort-v1','reviewed_by':'argilla:'+actor['id']+':'+actor['username'],
            'reviewed_at':now(),'confirm_group_review':True,'items':[{k:r[k] for k in ('source_ref_id','approval_id','event_group_ids','duplicate_group_ids','regions','language')}|{'sampling':None} for r in rows]}
        export_id='export-'+document_hash([body['experiment_id'],inv['inventory_sha256']])
        output=self.root/'exports'/export_id
        context=bridge.records(self.bridge_root)[0]
        if output.exists():manifest=validate_dataset(output)
        else:
            cohort_id=self.artifact('cohorts','cohort-',cohort)
            manifest=export_dataset(context['store'],self.root/'cohorts'/cohort_id/'manifest.json',output,seed=config['seed'])
        event=self.append('export',{'experiment_id':body['experiment_id'],'export_id':export_id,
            'manifest_id':manifest['manifest_id'],'readiness':manifest['readiness']},actor,body['expected_head'],body['request_id'])
        return {'event_id':event,'export_id':export_id,'readiness':manifest['readiness']}


def synthetic_fixture(output,seed=42):
    if type(seed) is not int:raise ValueError('An explicit integer fixture seed is required')
    rows=[]
    for i in range(60):
        label='defense' if i%2 else 'nondefense'
        rows.append({'fixture_id':f'fixture-{i:03}','synthetic':True,'group_id':f'fixture-group-{i//2:03}',
            'text':f'SYNTHETIC EDUCATIONAL FIXTURE {i}: '+('Fictional naval equipment evaluation.' if label=='defense' else 'Fictional market policy report.'),
            'fixture_target':label,'label_origin':'authored_synthetic_fixture_not_human_global_approval'})
    groups=list(range(30));random.Random(seed).shuffle(groups)
    assignment={g:('train' if n<21 else 'validation' if n<26 else 'test') for n,g in enumerate(groups)}
    payload=b''.join(encoded(r)+b'\n' for r in rows)
    manifest={'schema_version':'aic-synthetic-education-v1','seed':seed,'synthetic_only':True,
        'production_export_compatible':False,'human_approved':False,'training_executed':False,
        'fixture_sha256':digest(payload),'partitions':{s:[r['fixture_id'] for r in rows if assignment[int(r['group_id'].rsplit('-',1)[1])]==s] for s in SPLITS}}
    publish_directory(output,{'fixture.jsonl':payload,'manifest.json':encoded(manifest)})
    return manifest


def validate_fixture(output):
    from .global_io import parse_json
    path=Path(output);obj=read_object(path/'manifest.json');raw=(path/'fixture.jsonl').read_bytes()
    if obj['schema_version']!='aic-synthetic-education-v1' or obj['synthetic_only'] is not True or obj['production_export_compatible'] is not False or digest(raw)!=obj['fixture_sha256']:
        raise ValueError('Invalid segregated synthetic fixture')
    rows=[parse_json(line) for line in raw.decode().splitlines()];seen={};ids=set()
    keys(obj['partitions'],set(SPLITS),'fixture partitions')
    if obj.get('human_approved') is not False or obj.get('training_executed') is not False:
        raise ValueError('Synthetic fixtures cannot claim human approval or executed training')
    for value in obj['partitions'].values():unique_strings(value,'fixture membership')
    for row in rows:
        if row.get('synthetic') is not True or not row['fixture_id'].startswith('fixture-'):raise ValueError('Non-fixture record rejected')
        owners=[s for s in SPLITS if row['fixture_id'] in obj['partitions'][s]]
        if len(owners)!=1 or row['fixture_id'] in ids:raise ValueError('Fixture membership leakage')
        ids.add(row['fixture_id']);owner=owners[0]
        if row['group_id'] in seen and seen[row['group_id']]!=owner:raise ValueError('Fixture group leakage')
        seen[row['group_id']]=owner
    if set().union(*(set(v) for v in obj['partitions'].values()))!=ids:raise ValueError('Unknown fixture members')
    return {'valid':True,'synthetic_records':len(rows),'training_executed':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge-root',type=Path,default=Path('data/argilla'))
    parser.add_argument('--root',type=Path,default=Path('data/review_dashboard/research'))
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('summary');commands.add_parser('capture')
    fixture=commands.add_parser('fixture');fixture.add_argument('--output',type=Path,required=True);fixture.add_argument('--seed',type=int,default=42)
    fixture_check=commands.add_parser('validate-fixture');fixture_check.add_argument('directory',type=Path)
    check=commands.add_parser('validate-plan');check.add_argument('plan_id')
    args=parser.parse_args();ledger=ResearchLedger(args.bridge_root,args.root)
    try:
        if args.command=='fixture':result=synthetic_fixture(args.output,args.seed)
        elif args.command=='validate-fixture':result=validate_fixture(args.directory)
        elif args.command=='validate-plan':result=ledger.validate_plan(args.plan_id)
        elif args.command=='capture':result={'event_id':ledger.capture(SYSTEM,ledger.events()[1],str(uuid4()))}
        else:result=ledger.summary()
    except (OSError,ValueError,KeyError,TypeError) as exc:parser.exit(2,f'Research preparation rejected: {exc}\n')
    print(encoded(result).decode())


if __name__=='__main__':main()
