"""Explicitly permitted frozen retrieval indexes; never ingests training JSONL."""
from pathlib import Path
import numpy as np
from .content_reference import load_source
from .global_io import document_hash,encoded,keys,read_object,publish_directory,string,now
from .global_review import history,rights_status,DEFAULT_POLICY
from .inference_runtime import file_hash

PERMISSION_FIELDS={'schema_version','source','scope','permitted','reviewed_by','reviewed_at','handling_basis','synthetic_fixture'}

def check_permission(store,permission,*,allow_fixture=False):
    keys(permission,PERMISSION_FIELDS,'retrieval use permission')
    if (permission['schema_version']!='aic-processing-permission-v1' or permission['scope']!='local_inference_and_retrieval'
        or permission['permitted'] is not True or type(permission['synthetic_fixture']) is not bool
        or permission['synthetic_fixture'] and not allow_fixture):raise ValueError('No permitted real-source retrieval scope')
    from .global_io import timestamp
    timestamp(permission['reviewed_at'],'permission review UTC',utc=True)
    for key in ('reviewed_by','handling_basis'):string(permission[key],key)
    ref,text,binding=load_source(store,permission['source']['source_ref_id'])
    if rights_status(store,ref['source_ref_id']) not in {'unverified','cleared'}:raise ValueError('Restricted/conflicting source rights block experimental use')
    if permission['source']!=binding:raise ValueError('Stale content/permission/provenance')
    if not permission['synthetic_fixture'] and ('synthetic' in ref['metadata']['provenance_method'].lower() or ref['canonical_source_id'].startswith('https://example.')):
        raise ValueError('Synthetic fixtures cannot be published as real intelligence')
    return ref,text,binding

def build_index(store,permissions,output,runtime,*,version,allow_fixture=False):
    string(version,'index version')
    if not isinstance(permissions,list) or not 1<=len(permissions)<=1000:raise ValueError('Index needs 1-1000 explicit permissions')
    rows=[];seen=set()
    for permission in permissions:
        ref,text,binding=check_permission(store,permission,allow_fixture=allow_fixture)
        if ref['source_ref_id'] in seen:raise ValueError('Duplicate index source')
        seen.add(ref['source_ref_id'])
        rows.append({'source':binding,'permission':permission,'vector':runtime.embed(text).tolist()})
    manifest={'schema_version':'aic-retrieval-index-v1','version':version,'encoder':runtime.identity,'rows':rows}
    if len(encoded(manifest))>8*1024*1024:raise ValueError('Frozen index exceeds local reader size bound')
    publish_directory(output,{'index.json':encoded(manifest)})
    return file_hash(Path(output)/'index.json')

class RetrievalIndex:
    def __init__(self,path,expected_sha,store,runtime,*,allow_fixture=False):
        self.path=Path(path);self.expected=expected_sha;self.store=Path(store);self.runtime=runtime;self.allow_fixture=allow_fixture
        self.validate()

    def validate(self):
        if file_hash(self.path)!=self.expected:raise ValueError('Index digest mismatch')
        obj=read_object(self.path);keys(obj,{'schema_version','version','encoder','rows'},'retrieval index')
        if obj['schema_version']!='aic-retrieval-index-v1' or obj['encoder']!=self.runtime.identity or not 1<=len(obj['rows'])<=1000:
            raise ValueError('Incompatible index/encoder')
        seen=set()
        for row in obj['rows']:
            keys(row,{'source','permission','vector'},'index row')
            _,_,binding=check_permission(self.store,row['permission'],allow_fixture=self.allow_fixture)
            v=np.asarray(row['vector'],dtype=np.float64)
            if row['source']!=binding or binding['source_ref_id'] in seen or v.shape!=(384,) or not np.isfinite(v).all() or not np.isclose(np.linalg.norm(v),1,atol=1e-4):
                raise ValueError('Stale/invalid index row')
            seen.add(binding['source_ref_id'])
        self.obj=obj

    def resolve(self,source_ref_id,content_sha):
        self.validate()
        for row in self.obj['rows']:
            if row['source']['source_ref_id']==source_ref_id:
                ref,text,binding=check_permission(self.store,row['permission'],allow_fixture=self.allow_fixture)
                if binding['content_revision_sha256']!=content_sha:raise ValueError('Stale requested revision')
                return text,binding
        raise ValueError('No permission for requested registered content')

    def search(self,text,expected,top_k):
        self.validate()
        if expected!=self.expected:raise ValueError('Requested index revision mismatch')
        query=self.runtime.embed(text);rank=[]
        for row in self.obj['rows']:
            ref,content,binding=check_permission(self.store,row['permission'],allow_fixture=self.allow_fixture)
            rank.append({'source':binding,'source_url':ref['canonical_source_id'],'publisher':ref['metadata']['publisher'],
                'representation_type':ref['metadata']['content_type'],'excerpt':content[:600],
                'excerpt_start':0,'excerpt_end':len(content[:600]),'permission_sha256':document_hash(row['permission']),
                'synthetic_fixture':row['permission']['synthetic_fixture'],
                'similarity':float(np.clip(query@np.asarray(row['vector']),-1,1))})
        return sorted(rank,key=lambda r:(-r['similarity'],r['source']['source_ref_id']))[:top_k]

    def human_reference(self,binding):
        if any(r['source']==binding and r['permission']['synthetic_fixture'] for r in self.obj['rows']):return {'status':'unavailable'}
        approvals,heads=history(self.store)
        matches=[approvals[i] for i in heads.values() if approvals[i]['source']==binding]
        if len(matches)!=1:return {'status':'unavailable'}
        a=matches[0]
        if a['annotation_policy_sha256']!=document_hash(read_object(DEFAULT_POLICY)) or a['documents']['taxonomy']['version']!='aic-global-v2':return {'status':'unavailable'}
        return {'status':'matched_current_global_approval','approval_id':a['approval_id'],
            'annotation_policy_sha256':a['annotation_policy_sha256'],'taxonomy_sha256':a['taxonomy_sha256'],
            'defense_label':'defense' if 'defense' in a['annotation']['domains'] else 'nondefense',
            'source_binding':binding,'evidence_sha256':document_hash(a['annotation']['evidence'])}

def main():
    import argparse
    from .inference_runtime import Runtime
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--permissions',type=Path,required=True);p.add_argument('--store',type=Path,required=True)
    p.add_argument('--head',type=Path,required=True);p.add_argument('--head-sha256',required=True)
    p.add_argument('--encoder',type=Path,required=True);p.add_argument('--revision',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--version',required=True)
    p.add_argument('--confirm-permitted-use',action='store_true');p.add_argument('--allow-synthetic-fixtures',action='store_true')
    a=p.parse_args()
    if not a.confirm_permitted_use:p.error('Explicit permitted-use review required; training rights are not inferred')
    permissions=read_object(a.permissions);keys(permissions,{'schema_version','permissions'},'processing permissions')
    if permissions['schema_version']!='aic-processing-permissions-v1':p.error('Unsupported permission manifest')
    rt=Runtime(a.head,a.head_sha256,a.encoder,a.revision)
    print(build_index(a.store,permissions['permissions'],a.output,rt,version=a.version,allow_fixture=a.allow_synthetic_fixtures))

if __name__=='__main__':main()
