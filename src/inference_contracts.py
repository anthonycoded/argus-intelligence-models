"""Phase 3C wire contracts. Predictions/similarity never grant review or rights."""
import hashlib
from typing import Literal
from uuid import UUID,uuid4
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator

SCHEMA='aic-experimental-v1'
MAX_TEXT=16000

def text_hash(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()

class Contract(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False,hide_input_in_errors=True)

    @field_validator('request_id',mode='before',check_fields=False)
    @classmethod
    def canonical_request_id(cls,value):
        if isinstance(value,str):
            parsed=UUID(value)
            if str(parsed)!=value:raise ValueError('Canonical request UUID required')
            return parsed
        return value

class ContentInput(Contract):
    request_id:UUID=Field(default_factory=uuid4)
    article_id:str=Field(pattern=r'^[A-Za-z0-9_.:-]{1,128}$')
    text:str|None=Field(default=None,min_length=1,max_length=MAX_TEXT)
    source_ref_id:str|None=Field(default=None,pattern=r'^src-[0-9a-f]{64}$')
    content_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    authorized_for_processing:Literal[True]
    handling_basis:str=Field(min_length=1,max_length=256)

    @field_validator('authorized_for_processing',mode='before')
    @classmethod
    def explicit_authorization(cls,value):
        if value is not True:raise ValueError('Explicit processing authorization required')
        return value

    @model_validator(mode='after')
    def content_binding(self):
        if (self.text is None)==(self.source_ref_id is None):raise ValueError('Supply exactly text or a registered reference')
        if self.text is not None and (not self.text.strip() or text_hash(self.text)!=self.content_sha256):
            raise ValueError('Exact UTF-8 content digest mismatch or empty text')
        if not self.handling_basis.strip():raise ValueError('Processing basis is required')
        return self

class RetrievalInput(ContentInput):
    index_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    top_k:int=Field(default=5,ge=1,le=10)

class EncoderIdentity(Contract):
    name:Literal['sentence-transformers/all-MiniLM-L6-v2']
    revision:str=Field(pattern=r'^[0-9a-f]{40}$')
    directory_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    dimension:Literal[384]
    max_sequence_length:Literal[256]
    normalized:Literal[True]

class Execution(Contract):
    id:UUID
    duration_ms:float=Field(ge=0,le=3600000)
    device:Literal['cpu']='cpu'

class HumanReference(Contract):
    status:Literal['unavailable','matched_current_global_approval']
    approval_id:str|None=None
    annotation_policy_sha256:str|None=None
    taxonomy_sha256:str|None=None
    defense_label:Literal['defense','nondefense']|None=None
    source_binding:dict[str,str]|None=None
    evidence_sha256:str|None=None

    @model_validator(mode='after')
    def complete_binding(self):
        fields=(self.approval_id,self.annotation_policy_sha256,self.taxonomy_sha256,self.defense_label,self.source_binding,self.evidence_sha256)
        if self.status=='matched_current_global_approval' and any(v is None for v in fields):raise ValueError('Incomplete human approval binding')
        if self.status=='unavailable' and any(v is not None for v in fields):raise ValueError('Unavailable gold must not supply labels')
        return self

class Classification(Contract):
    schema_version:Literal['aic-experimental-v1']=SCHEMA
    experimental:Literal[True]=True
    operational_authority:Literal[False]=False
    probability_calibrated:Literal[False]=False
    task:Literal['global_defense_v1']='global_defense_v1'
    training_origin:Literal['synthetic_v2','synthetic_fixture']
    request_id:UUID
    article_id:str
    content_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    classifier_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    source_artifact_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    encoder:EncoderIdentity
    defense_score:float=Field(ge=0,le=1)
    threshold:float=Field(ge=0,le=1)
    prediction:Literal['defense','nondefense']
    human_reference:HumanReference
    execution:Execution

    @model_validator(mode='after')
    def threshold_consistency(self):
        if self.prediction!=('defense' if self.defense_score>=self.threshold else 'nondefense'):
            raise ValueError('Prediction/threshold mismatch')
        return self
