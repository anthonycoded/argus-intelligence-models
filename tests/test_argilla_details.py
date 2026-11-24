"""Target mappings are explicit; all production responses remain read-only."""
from copy import deepcopy

import pytest

from tests.test_argilla_bridge import bridge,attach,answers,submit
from tests.test_argilla_staging_errors import economic_article
from src import argilla_bridge as b
from src import argilla_details as helper
from src.global_io import digest,read_object
from src.global_review import load_draft
from src.global_review import approve


def saved_economics(c,extra=False,duplicate=False):
    attach(c)
    annotation=economic_article(c)
    e=annotation['evidence'][0]
    values=answers(annotation)
    values['evidence_spans']=[{'start':e['start'],'end':e['end'],'label':'support'}]
    if extra: values['evidence_spans'].append({'start':0,'end':10,'label':'support'})
    if duplicate: values['evidence_spans'].append(deepcopy(values['evidence_spans'][0]))
    return submit(c,values),annotation


def test_existing_target_projection_stages_without_assigning_extra_highlight(bridge):
    c=bridge
    submission,article=saved_economics(c,extra=True)
    before=deepcopy([vars(r) for r in c['remote'].records])
    with pytest.raises(ValueError,match='Native span must correspond'):
        b.stage(c['bridge'],submission)
    result=helper.stage_existing_evidence(c['bridge'],submission)
    assert result['selected_span_indexes']==[0] and result['unassigned_span_indexes']==[1]
    assert result['annotation_changes']==[]
    assert load_draft(c['root'],result['draft_id'])['annotation']==article
    assert helper.stage_existing_evidence(c['bridge'],submission)==result
    assert before==[vars(r) for r in c['remote'].records]
    assert not (c['root']/'approvals').exists() and not (c['root']/'rights').exists()
    with pytest.raises(ValueError,match='confirm-human-review'):
        approve(c['root'],result['draft_id'],'synthetic-reviewer')
    # The legacy contract is intentionally unchanged, not silently relaxed.
    with pytest.raises(ValueError,match='Native span must correspond'):
        b.stage(c['bridge'],submission)


def test_new_mappings_require_explicit_reviewer_confirmation(bridge,tmp_path):
    c=bridge
    submission,_=saved_economics(c)
    output=tmp_path/'proposal'
    with pytest.raises(ValueError,match='confirm-evidence-mapping'):
        helper.prepare_details(c['bridge'],submission,[{'span_index':0,'target':'/domains/0'}],
                               'Synthetic source attribution',output)
    assert not output.exists() and not (c['root']/'drafts').exists()


def test_confirmed_form_is_idempotent_deduplicated_and_does_not_write_responses(bridge,tmp_path):
    c=bridge
    submission,article=saved_economics(c,duplicate=True)
    before=deepcopy([vars(r) for r in c['remote'].records])
    choices=[{'span_index':0,'target':'/domains/0'},{'span_index':1,'target':'/domains/0'}]
    args=(c['bridge'],submission,choices,'Synthetic test source',tmp_path/'proposal')
    result=helper.prepare_details(*args,confirm=True)
    assert helper.prepare_details(*args,confirm=True)==result
    details=read_object(tmp_path/'proposal/details.json')
    assert len(details['evidence'])==1 and details=={k:article[k] for k in b.DETAIL_FIELDS}
    assert before==[vars(r) for r in c['remote'].records]
    assert not (c['root']/'drafts').exists() and not (c['root']/'approvals').exists()


@pytest.mark.parametrize('change',['span','quote','hash','target'])
def test_projection_rejects_mismatched_or_forged_evidence(bridge,change):
    c=bridge
    submission,article=saved_economics(c)
    if change=='span': article['evidence'][0]['start']+=1
    elif change=='quote': article['evidence'][0]['quote']='forged'
    elif change=='hash': article['evidence'][0]['content_revision_sha256']='0'*64
    else:article['evidence'][0]['target']='/invented/claim'
    values=answers(article)
    # Retain the genuine selected native range, changing only supplemental transcription.
    current=helper.saved_response(c['bridge'],submission)[1]
    values['evidence_spans']=current['answers']['evidence_spans']
    changed=submit(c,values)
    with pytest.raises(ValueError):helper.stage_existing_evidence(c['bridge'],changed)
    assert not (c['root']/'drafts').exists()


@pytest.mark.parametrize('change',['content','head','withdrawn'])
def test_stale_bindings_rejected_before_projection_or_new_form(bridge,tmp_path,change):
    c=bridge;submission,_=saved_economics(c)
    if change=='content':
        p=c['root']/'sources'/c['source']/'content.utf8';p.write_bytes(p.read_bytes()+b'changed')
    elif change=='head':
        c['text_file'].write_bytes(c['text_file'].read_bytes()+b'new revision')
        attach(c)
    else:submit(c,status='draft')
    with pytest.raises(ValueError):helper.stage_existing_evidence(c['bridge'],submission)
    with pytest.raises(ValueError):
        helper.prepare_details(c['bridge'],submission,[{'span_index':0,'target':'/domains/0'}],
                               'Synthetic',tmp_path/'proposal',confirm=True)


def test_new_economics_template_has_no_inferred_entities_or_event_instances(bridge,tmp_path):
    c=bridge;submission,_=saved_economics(c)
    result=helper.prepare_details(c['bridge'],submission,[{'span_index':0,'target':'/domains/0'}],
        'Synthetic source',tmp_path/'proposal',confirm=True,new_article_template=True,
        scope_note='Human chose article-only annotation; individual events not enumerated.')
    details=read_object(result['details_file'])
    assert set(details)==b.DETAIL_FIELDS
    assert details['countries']==details['organizations']==details['events']==[]
    assert details['event_date'] is None and details['event_location'] is None
    assert details['evidence_status']=='unknown'
    assert not (c['root']/'approvals').exists()


def test_unicode_native_mapping_uses_exact_registered_text(bridge,tmp_path):
    c=bridge
    # Use a new content-view revision with astral/combining characters and CRLF.
    text='😀 e\u0301\r\nTrade agreement cut tariffs.'
    c['text_file'].write_bytes(text.encode())
    b.attach(c['bridge'],c['row']['candidate_id'],c['text_file'],'human_summary',c['metadata']['rights_note'],content_view=True)
    article=economic_article(c)
    start=text.index('Trade');end=len(text)
    article['evidence']=[{'target':'/domains/0','content_revision_sha256':digest(text.encode()),
                         'start':start,'end':end,'quote':text[start:end],'attribution':'Synthetic'}]
    values=answers(article)
    values['evidence_spans']=[{'start':len(text[:start].encode('utf-16-le'))//2,
                              'end':len(text.encode('utf-16-le'))//2,'label':'support'}]
    submission=submit(c,values)
    result=helper.prepare_details(c['bridge'],submission,[{'span_index':0,'target':'/domains/0'}],
                                  'Synthetic',tmp_path/'proposal',confirm=True)
    evidence=read_object(result['details_file'])['evidence'][0]
    assert evidence['start']==start and evidence['end']==end and evidence['quote']==text[start:end]
    assert helper.stage_existing_evidence(c['bridge'],submission)['state']=='validated_draft_not_approved'


def test_blank_article_template_has_eight_fields_and_cannot_stage_alone():
    template=helper.article_template('REVIEWER MUST COMPLETE SCOPE')
    assert set(template)==b.DETAIL_FIELDS and template['evidence']==[]
    with pytest.raises(ValueError):helper.article_template('')
