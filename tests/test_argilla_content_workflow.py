"""Content revisions and real human span mappings; no network or SDK imports."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.test_argilla_bridge import bridge, Record, USER, answers, submit
from src import argilla_bridge as b
from src.global_io import digest


def sync(c):
    return b.attach_and_sync(c['bridge'], c['remote'], SimpleNamespace(Record=Record), c['client'],
                             c['row']['candidate_id'], c['text_file'], 'human_summary', c['metadata']['rights_note'])


def test_attach_sync_preserves_existing_human_draft_and_all_old_fields(bridge):
    c = bridge
    first = submit(c, status='draft')
    old = c['remote'].records[0]
    fields, metadata, responses = deepcopy(old.fields), deepcopy(old.metadata), deepcopy(old.responses)
    result = sync(c)
    assert result['added']==1 and result['re_review_required']
    assert old.fields==fields and old.metadata==metadata
    assert [vars(a) for a in old.responses]==[vars(a) for a in responses]
    current = next(r for r in c['remote'].records if r.id==result['record_id'])
    assert current.fields['text']==c['text']
    assert current.responses==[]  # Never impersonate the original reviewer on new content.
    assert 'RE-REVIEW REQUIRED' in current.fields['context']
    assert USER in current.fields['context'] and 'military_exercise' in current.fields['context']
    assert 'human_summary' in current.fields['context']
    assert '[Open original publisher source]' in current.fields['source']
    assert sync(c)['added']==0
    assert len(c['remote'].records)==2
    assert b._read(c['bridge'],'submissions',first,'submission-')['status']=='draft'


@pytest.mark.parametrize('raw',[b'',b' \r\n\t',b'\xff',b'x'*(2*1024*1024+1)])
def test_empty_unauthorized_encoding_or_oversize_content_never_registers(bridge,raw):
    c=bridge
    c['text_file'].write_bytes(raw)
    before=b.records(c['bridge'])
    with pytest.raises((ValueError,UnicodeError)):
        sync(c)
    assert b.records(c['bridge'])==before
    assert not (c['bridge']/'stages').exists()


def test_stale_old_draft_cannot_supply_evidence_after_attachment(bridge):
    c=bridge
    original=submit(c,status='draft')
    sync(c)
    with pytest.raises(ValueError,match='Stale representation'):
        b.evidence_from_span(c['bridge'],original,0,'/domains/0','Synthetic attribution')


@pytest.mark.parametrize('text,start,end,expected,byte_range',[
    ('😀 café\r\nZulu',3,7,'café',(5,10)),
    ('e\u0301 text',0,2,'e\u0301',(0,3)),
    ('\ufeffA\r\nB',4,5,'B',(6,7)),
])
def test_utf16_span_to_unicode_and_exact_utf8_bytes(text,start,end,expected,byte_range):
    span=b.span_offsets(text,start,end)
    assert span['quote']==expected
    assert text[span['start']:span['end']]==expected
    raw=text.encode('utf-8')
    assert raw[span['utf8_byte_start']:span['utf8_byte_end']].decode()==expected
    assert (span['utf8_byte_start'],span['utf8_byte_end'])==byte_range


@pytest.mark.parametrize('start,end',[(0,1),(1,2),(0,999),(True,2),(-1,2),(2,2)])
def test_invalid_surrogate_or_out_of_range_offsets_rejected(start,end):
    with pytest.raises(ValueError):
        b.span_offsets('😀text',start,end)


def test_native_highlight_mapping_and_staging_use_same_registered_revision(bridge):
    c=bridge
    sync(c)
    annotation=deepcopy(c['annotation'])
    values=answers(annotation)
    values['evidence_spans']=[{'start':0,'end':len(c['text'].encode('utf-16-le'))//2,'label':'support'}]
    submission=submit(c,values,status='draft')
    evidence=b.evidence_from_span(c['bridge'],submission,0,'/domains/0','Synthetic test attribution')
    assert evidence['evidence']['content_revision_sha256']==digest(c['text_file'].read_bytes())
    assert evidence['evidence']['quote']==c['text']
    assert evidence['utf8_byte_range']['end']==len(c['text_file'].read_bytes())
    submitted=submit(c,values,status='submitted')
    assert b.stage(c['bridge'],submitted)['state']=='validated_draft'
    c['text_file'].write_bytes(c['text_file'].read_bytes()+b'\nA different revision.')
    sync(c)
    with pytest.raises(ValueError,match='Stale representation'):
        b.evidence_from_span(c['bridge'],submitted,0,'/domains/0','Synthetic attribution')
    with pytest.raises(ValueError,match='Stale or unknown'):
        b.stage(c['bridge'],submitted)


def test_pending_content_cannot_generate_evidence(bridge):
    submission=submit(bridge,status='draft')
    with pytest.raises(ValueError,match='Pending/empty'):
        b.evidence_from_span(bridge['bridge'],submission,0,'/domains/0','No fabricated evidence')


def test_absent_or_forged_highlight_is_not_invented(bridge):
    c=bridge
    sync(c)
    submission=submit(c,status='draft')
    with pytest.raises(ValueError,match='existing saved'):
        b.evidence_from_span(c['bridge'],submission,0,'/domains/0','Synthetic')
    values=answers(c['annotation'])
    values['evidence_spans']=[{'start':0,'end':999999,'label':'support'}]
    submitted=submit(c,values)
    with pytest.raises(ValueError):
        b.evidence_from_span(c['bridge'],submitted,0,'/domains/0','Synthetic')
    with pytest.raises(ValueError):
        b.stage(c['bridge'],submitted)
