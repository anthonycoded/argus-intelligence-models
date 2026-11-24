"""Exact quote transcription repair and Windows clipboard UTF-8 regressions."""
from copy import deepcopy
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.test_argilla_bridge import bridge,attach,answers,submit
from src import argilla_details as helper
from src.global_review import load_draft
from src.global_io import digest


def evidence_case():
    text="Allies evaluated the consortium\u2019s missile portfolio.\nA second statement."
    end=text.index('\n')
    item={'target':'/domains/0','content_revision_sha256':digest(text.encode()),
          'start':0,'end':end,'quote':text[:end],'attribution':'Actual synthetic source attribution'}
    spans=[{'start':0,'end':end,'label':'support'}]
    return text,item,spans


def test_curly_apostrophe_is_quote_mojibake_not_a_byte_offset_error():
    text,item,spans=evidence_case()
    original=deepcopy(item)
    item['quote']=item['quote'].encode('utf-8').decode('cp1252')
    corrected,changes=helper.repair_quote_encoding({'evidence':[item]},spans,text,digest(text.encode()))
    assert corrected['evidence']==[original]
    assert len(changes)==1 and changes[0]['path']=='/evidence/0/quote'
    assert item['quote']!=original['quote']  # Original untouched.
    assert len(text[:original['end']].encode())==original['end']+2


@pytest.mark.parametrize('mutation',['ascii_apostrophe','different_quote','hash','byte_offsets','absent_highlight'])
def test_repair_never_guesses_missing_human_choices_or_stale_coordinates(mutation):
    text,item,spans=evidence_case()
    item['quote']=item['quote'].encode('utf-8').decode('cp1252')
    if mutation=='ascii_apostrophe': item['quote']=text[:item['end']].replace('\u2019',"'")
    elif mutation=='different_quote': item['quote']='An unrelated claim'
    elif mutation=='hash': item['content_revision_sha256']='0'*64
    elif mutation=='byte_offsets': item['end']+=2
    else: spans=[]
    with pytest.raises(ValueError):
        helper.repair_quote_encoding({'evidence':[item]},spans,text,digest(text.encode()))


def test_exact_quotes_are_not_rewritten():
    text,item,spans=evidence_case()
    corrected,changes=helper.repair_quote_encoding({'evidence':[item]},spans,text,digest(text.encode()))
    assert corrected=={'evidence':[item]} and changes==[]


def test_audited_repair_stages_once_and_preserves_saved_rationale_scope_and_responses(bridge):
    c=bridge;attach(c)
    values=answers(c['annotation'])
    details=json.loads(values['details'])
    for entry in details['evidence']:
        entry['quote']=entry['quote'].encode('utf-8').decode('cp1252')
    values['details']=json.dumps(details)
    values['evidence_spans']=[{'start':0,'end':len(c['text']),'label':'support'}]
    submission=submit(c,values)
    before=deepcopy([vars(r) for r in c['remote'].records])
    with pytest.raises(ValueError,match='Forged/stale'):
        helper.stage_existing_evidence(c['bridge'],submission)
    result=helper.stage_existing_evidence(c['bridge'],submission,repair_encoding=True)
    assert result['annotation_changes']
    assert load_draft(c['root'],result['draft_id'])['annotation']==c['annotation']
    assert helper.stage_existing_evidence(c['bridge'],submission,repair_encoding=True)==result
    assert before==[vars(r) for r in c['remote'].records]
    assert not (c['root']/'approvals').exists() and not (c['root']/'rights').exists()


@pytest.mark.skipif(shutil.which('powershell') is None,reason='Windows PowerShell integration check')
@pytest.mark.parametrize('invalid',[False,True])
def test_clipboard_helper_uses_strict_utf8_without_touching_real_clipboard(tmp_path,invalid):
    source=tmp_path/'details.json';output=tmp_path/'captured.txt'
    value=json.dumps({'quote':'consortium\u2019s \U0001f600 cafe\u0301\r\n'},ensure_ascii=False)
    source.write_bytes(b'\xff' if invalid else value.encode('utf-8'))
    code="""
$ErrorActionPreference='Stop'
function Set-Clipboard { param([string]$Value) [IO.File]::WriteAllText($env:AIC_TEST_OUTPUT,$Value,[Text.UTF8Encoding]::new($false)) }
try { & $env:AIC_TEST_COPY_SCRIPT -ContentPath $env:AIC_TEST_INPUT } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 7 }
"""
    encoded=base64.b64encode(code.encode('utf-16-le')).decode('ascii')
    env={**os.environ,'AIC_TEST_INPUT':str(source),'AIC_TEST_OUTPUT':str(output),
         'AIC_TEST_COPY_SCRIPT':str(Path('deploy/argilla/Copy-Details.ps1').resolve())}
    # Child-process policy only: permit this local workspace script, never alter
    # machine/user policy or execute downloaded scripts.
    result=subprocess.run(['powershell','-NoProfile','-NonInteractive','-ExecutionPolicy','RemoteSigned','-EncodedCommand',encoded],
                          env=env,capture_output=True,timeout=30)
    if invalid:
        assert result.returncode==7 and not output.exists()
    else:
        assert result.returncode==0,result.stderr.decode(errors='replace')
        assert output.read_bytes()==value.encode('utf-8')
