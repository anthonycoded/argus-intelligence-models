"""Pinned local encoder + numeric logistic head. Never imports training scripts."""
import argparse
import hashlib
import importlib.metadata
import math
import os
from pathlib import Path
import numpy as np
from .global_io import document_hash,encoded,keys,read_object,publish_directory
from .inference_contracts import EncoderIdentity

NAME='sentence-transformers/all-MiniLM-L6-v2'

def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def encoder_identity(directory,revision):
    directory=Path(directory)
    if not directory.is_dir() or directory.name!=revision:raise ValueError('Pinned snapshot directory/revision required')
    required={'model.safetensors','config.json','modules.json','tokenizer.json','1_Pooling/config.json','sentence_bert_config.json'}
    files={p.relative_to(directory).as_posix():file_hash(p) for p in sorted(directory.rglob('*')) if p.is_file()}
    if not required<=set(files) or any(p.endswith(('.py','.bin','.pkl','.joblib')) for p in files):raise ValueError('Unsupported local encoder layout')
    config=read_object(directory/'config.json');preprocessing=read_object(directory/'sentence_bert_config.json')
    if config.get('model_type')!='bert' or config.get('hidden_size')!=384 or preprocessing.get('max_seq_length')!=256:
        raise ValueError('Unsupported MiniLM architecture/preprocessing')
    from .global_io import parse_json
    modules=parse_json((directory/'modules.json').read_text())
    allowed={'sentence_transformers.models.Transformer','sentence_transformers.models.Pooling','sentence_transformers.models.Normalize'}
    if any(m.get('type') not in allowed or '..' in m.get('path','') for m in modules):raise ValueError('Untrusted encoder module')
    return EncoderIdentity(name=NAME,revision=revision,directory_sha256=document_hash(files),dimension=384,max_sequence_length=256,normalized=True).model_dump()

class Runtime:
    def __init__(self,head_path,expected_head_sha256,encoder_path,revision,*,encoder_factory=None):
        head_path=Path(head_path)
        if head_path.suffix!='.json' or file_hash(head_path)!=expected_head_sha256:raise ValueError('Missing/mismatched numeric head')
        head=read_object(head_path)
        keys(head,{'schema_version','encoder','coefficients','intercept','classes','threshold','training_origin','source_artifact_sha256','packages','dataset_sha256','split_sha256'},'numeric classifier')
        if (head['schema_version']!='aic-numeric-defense-v1' or head['classes']!=[0,1]
            or any(type(v) is not int for v in head['classes']) or head['training_origin'] not in {'synthetic_v2','synthetic_fixture'}):
            raise ValueError('Unsupported classifier contract')
        self.identity=encoder_identity(encoder_path,revision)
        if head['encoder']!=self.identity:raise ValueError('Classifier/encoder identity mismatch')
        coefficients=head['coefficients']
        if (not isinstance(coefficients,list) or len(coefficients)!=384 or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1e6 for v in coefficients)
            or type(head['intercept']) not in (int,float) or not math.isfinite(head['intercept']) or abs(head['intercept'])>1e6
            or type(head['threshold']) not in (int,float) or not 0<head['threshold']<1):raise ValueError('Invalid logistic parameters')
        from .global_io import hash_string
        for key in ('source_artifact_sha256','dataset_sha256','split_sha256'):hash_string(head[key],key)
        self.head=head;self.head_sha256=expected_head_sha256
        self.weights=np.asarray(coefficients,dtype=np.float64)
        os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
        if encoder_factory is None:
            import torch
            torch.set_num_threads(1)
            from sentence_transformers import SentenceTransformer
            self.encoder=SentenceTransformer(str(Path(encoder_path).resolve()),device='cpu',local_files_only=True,
                trust_remote_code=False,model_kwargs={'use_safetensors':True})
        else:self.encoder=encoder_factory()
        self.encoder.max_seq_length=256

    def embed(self,text):
        value=np.asarray(self.encoder.encode([text],normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False),dtype=np.float64)
        if value.shape!=(1,384) or not np.isfinite(value).all() or not np.isclose(np.linalg.norm(value[0]),1,atol=1e-4):raise ValueError('Invalid encoder vector')
        return value[0]

    def classify(self,text):
        x=float(self.embed(text)@self.weights+self.head['intercept'])
        return 1/(1+math.exp(-x)) if x>=0 else math.exp(x)/(1+math.exp(x))

def convert_trusted_head(path,expected,encoder_path,revision,output,*,confirm=False):
    """Legacy entry point disabled: conversion requires a separate sandbox controller."""
    if confirm is not True:raise ValueError('Explicit locally trusted artifact confirmation required')
    raise ValueError('Host pickle conversion disabled; use tools/convert_head_isolated.py with an inspected offline container')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--joblib',type=Path,required=True);p.add_argument('--expected-sha256',required=True)
    p.add_argument('--encoder',type=Path,required=True);p.add_argument('--revision',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--confirm-trusted-local-artifact',action='store_true');a=p.parse_args()
    print(convert_trusted_head(a.joblib,a.expected_sha256,a.encoder,a.revision,a.output,confirm=a.confirm_trusted_local_artifact))

if __name__=='__main__':main()
