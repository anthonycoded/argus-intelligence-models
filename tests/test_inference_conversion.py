"""Conversion boundary tests never deserialize pickle or start containers."""
import builtins
from copy import deepcopy
import math
import pytest
from tools.convert_head_isolated import probes, validate_projection
from src.inference_runtime import convert_trusted_head


def projection():
    weights=[.01]*384;bias=.2;vectors=probes()
    scores=[sum(x*y for x,y in zip(v,weights))+bias for v in vectors]
    probabilities=[1/(1+math.exp(-s)) for s in scores]
    return vectors,{'coefficients':weights,'intercept':bias,'classes':[0,1],
        'probabilities':[[1-p,p] for p in probabilities],
        'predictions':[int(s>0) for s in scores],'packages':{}}


def test_legacy_converter_never_deserializes_even_with_confirmation(monkeypatch,tmp_path):
    original=builtins.__import__
    def guarded(name,*args,**kwargs):
        if name in {'joblib','pickle','sklearn'}:pytest.fail('Host deserialization prohibited')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',guarded)
    with pytest.raises(ValueError,match='Host pickle conversion disabled'):
        convert_trusted_head(tmp_path/'head.joblib','a'*64,tmp_path,'1'*40,tmp_path/'output',confirm=True)


def test_fixed_probe_parity_is_deterministic_and_reports_tolerance():
    vectors,result=projection()
    assert vectors==probes()
    evidence=validate_projection(result,vectors)
    assert evidence['predictions_equal'] and evidence['probe_count']==19
    assert evidence['maximum_absolute_probability_error']<evidence['absolute_tolerance']==1e-10


@pytest.mark.parametrize('change',['weights','classes','probabilities','predictions','nonfinite','extra'])
def test_parity_and_numeric_validation_fail_closed(change):
    vectors,result=projection();result=deepcopy(result)
    if change=='weights':result['coefficients'].pop()
    if change=='classes':result['classes']=[1,0]
    if change=='probabilities':result['probabilities'][0]=[.9,.1]
    if change=='predictions':result['predictions'][0]=0
    if change=='nonfinite':result['intercept']=float('nan')
    if change=='extra':result['executable']='not allowed'
    with pytest.raises(ValueError):validate_projection(result,vectors)
