"""Versioned, human-declared AI text origin. No generation or rights inference."""
import re
from pathlib import Path
from .candidate_import import canonical_source
from .global_io import document_hash,hash_string,keys,read_object,string

POLICY=Path(__file__).resolve().parents[1]/'policies/representation_v2.json'
ORIGIN_FIELDS={'schema_version','policy_version','policy_sha256','generation_method','source_reference',
    'model_provider','model_name','human_editing_status','human_review_status','original_content_revision_sha256'}


def origin_document(values):
    policy=read_object(POLICY)
    return {**values,'schema_version':policy['ai_origin_schema'],'policy_version':policy['policy_version'],'policy_sha256':document_hash(policy)}


def validate_origin(origin,source_url):
    keys(origin,ORIGIN_FIELDS,'AI-assisted origin');policy=read_object(POLICY)
    if (origin['schema_version']!=policy['ai_origin_schema'] or origin['policy_version']!=policy['policy_version']
        or origin['policy_sha256']!=document_hash(policy)):
        raise ValueError('AI representation policy identity mismatch')
    string(origin['source_reference'],'original publisher source reference')
    if origin['source_reference']!=source_url:raise ValueError('AI source reference must match the registered publisher source URL')
    for field,choices in [('generation_method','generation_methods'),('human_editing_status','human_editing_statuses'),('human_review_status','human_review_statuses')]:
        if origin[field] not in policy[choices]:raise ValueError('Unsupported AI origin '+field)
    if (origin['generation_method']=='ai_generated_human_edited')!=(origin['human_editing_status']=='edited'):
        raise ValueError('AI generation method and editing status disagree')
    for field in ('model_provider','model_name'):
        if origin[field] is not None:string(origin[field],field)
    if origin['original_content_revision_sha256'] is not None:hash_string(origin['original_content_revision_sha256'],'original content revision')


def check_original(root,metadata,ancestors=None):
    origin=metadata.get('representation_provenance')
    if not origin or origin['original_content_revision_sha256'] is None:return
    from .content_reference import load_source
    revision=origin['original_content_revision_sha256'];canonical=canonical_source(metadata['source_id'])
    ident='src-'+document_hash([canonical,revision]);directory=Path(root)/'sources'/ident
    if not directory.exists():raise ValueError('Missing original AI input content revision')
    reference,_,_=load_source(root,ident,_ancestors=ancestors)
    if reference['canonical_source_id']!=canonical or reference['content_revision_sha256']!=revision:
        raise ValueError('Missing/stale original AI input content revision')


def leakage_flags(text):
    return [{'kind':'suspected_label_leakage','rule':pattern} for pattern in read_object(POLICY)['leakage_patterns'] if re.search(pattern,text,re.I)]
