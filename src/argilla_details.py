"""Small offline evidence form/projection helpers; never edit Argilla or approve.

Native highlights are review aids. Only explicit human-selected target mappings
become supplemental evidence; unassigned highlights remain in the immutable export.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from uuid import UUID

from . import argilla_bridge as bridge
from .content_reference import check_binding
from .global_io import (document_hash, encoded, keys, publish_directory, read_object,
                        string)
from .global_review import create_draft, load_draft


def saved_response(root, submission_id, *, submitted=False):
    context, items, heads = bridge.records(root)
    obj = bridge._read(root, 'submissions', submission_id, 'submission-')
    keys(obj, {'schema_version','record_id','reviewer_id','reviewer_username','status','answers'}, 'saved response')
    if obj['schema_version'] != 'aic-argilla-submission-v1':
        raise ValueError('Unsupported saved response schema')
    UUID(obj['reviewer_id'])
    string(obj['reviewer_username'], 'saved response author')
    _, snapshot = bridge._export_head(root)
    if snapshot is None or submission_id not in snapshot['submissions']:
        raise ValueError('Stale/withdrawn response; export current responses')
    if obj['status'] not in ({'submitted'} if submitted else {'draft','submitted'}):
        raise ValueError('A saved submitted response is required' if submitted else 'A saved draft/submitted response is required')
    item = items.get(obj['record_id'])
    if item is None or heads[item['candidate']['candidate_id']] != obj['record_id']:
        raise ValueError('Stale content representation; re-review the current text')
    if item['source'] is None:
        raise ValueError('Pending content cannot supply evidence')
    ref, text = check_binding(context['store'], item['source'])
    spans = obj['answers'].get('evidence_spans', [])
    # All native spans must be well formed, even if some are unassigned.
    if item.get('presentation') == bridge.PRESENTATION:
        normalized = bridge.normalized_spans(text, spans)
    else:
        if not isinstance(spans,list):
            raise ValueError('Malformed native span collection')
        normalized = []
        for span in spans:
            keys(span, {'start','end','label'}, 'native span')
            if span['label'] != 'support':
                raise ValueError('Unknown native span label')
            bridge.span_offsets(text,span['start'],span['end'],unit='codepoint')
            normalized.append(dict(span))
    return context, obj, item, ref, text, normalized


def article_template(scope_note):
    string(scope_note, 'explicit article-level scope note')
    return {'countries':[], 'organizations':[], 'event_date':None, 'event_location':None,
            'evidence_status':'unknown', 'event_coverage_note':scope_note,
            'events':[], 'evidence':[]}


def _projection(answers, details, spans, text, revision):
    selected, unassigned = [], []
    evidence = details.get('evidence')
    if not isinstance(evidence,list) or not evidence:
        raise ValueError('details.evidence: explicit targeted source evidence is required')
    positions = {(s['start'],s['end']) for s in spans}
    for entry in evidence:
        if not isinstance(entry,dict) or (entry.get('start'),entry.get('end')) not in positions:
            raise ValueError('Supplemental evidence must match an existing saved native highlight')
    used = {(e['start'],e['end']) for e in evidence}
    for index, span in enumerate(spans):
        (selected if (span['start'],span['end']) in used else unassigned).append(index)
    projected = deepcopy(answers)
    projected['details'] = encoded(details).decode()
    projected['evidence_spans'] = [spans[i] for i in selected]
    annotation = bridge.map_answers(projected,text,revision)
    return annotation, selected, unassigned


def repair_quote_encoding(details, spans, text, revision):
    """Only reverse an exact UTF-8-as-CP1252 transcription, never guess new evidence."""
    corrected=deepcopy(details)
    positions={(s['start'],s['end']) for s in spans}
    changes=[]
    for index,entry in enumerate(corrected['evidence']):
        if not isinstance(entry,dict):
            raise ValueError('Malformed evidence object')
        start,end=entry.get('start'),entry.get('end')
        if type(start) is not int or type(end) is not int or (start,end) not in positions:
            raise ValueError('Encoding repair requires exact saved highlight coordinates')
        if entry.get('content_revision_sha256')!=revision:
            raise ValueError('Encoding repair cannot change or bypass a stale content hash')
        expected=text[start:end]
        stored=entry.get('quote')
        if stored==expected:
            continue
        if not isinstance(stored,str):
            raise ValueError('Encoding repair requires a saved quote string')
        try:
            forward=expected.encode('utf-8').decode('cp1252')
            reverse=stored.encode('cp1252').decode('utf-8')
        except UnicodeError:
            raise ValueError('Quote mismatch is not the supported reversible encoding error; reviewer correction required') from None
        if forward!=stored or reverse!=expected:
            raise ValueError('Quote mismatch is not an exact UTF-8-as-CP1252 transcription; reviewer correction required')
        entry['quote']=expected
        changes.append({'path':f'/evidence/{index}/quote','repair':'reverse_exact_utf8_misdecoded_as_cp1252',
                        'start':start,'end':end,'old_quote_sha256':document_hash(stored),
                        'corrected_quote_sha256':document_hash(expected),
                        'target_offsets_hash_and_attribution_unchanged':True})
    return corrected,changes


def prepare_details(root, submission_id, mappings, attribution, output, *,
                    confirm=False, new_article_template=False, scope_note=None):
    """Human-confirmed target choices -> exact evidence JSON; output only, no API writes."""
    if confirm is not True:
        raise ValueError('Explicit --confirm-evidence-mapping required from the actual reviewer; this is not approval')
    context, obj, item, ref, text, spans = saved_response(root,submission_id)
    string(attribution,'human-selected source attribution')
    if new_article_template:
        if obj['answers'].get('event_coverage') != 'not_enumerated':
            raise ValueError('A new article-level template requires the reviewer to select not_enumerated')
        details = article_template(scope_note)
    else:
        details = bridge.parse_details(obj['answers'].get('details'))
    if not isinstance(mappings,list) or not mappings:
        raise ValueError('Explicit saved span-index / claim-target mappings are required')
    evidence, seen = [], set()
    for mapping in mappings:
        keys(mapping,{'span_index','target'},'human evidence mapping')
        index,target=mapping['span_index'],mapping['target']
        if type(index) is not int or not 0 <= index < len(spans):
            raise ValueError('Mapping references an absent saved native highlight')
        string(target,'human-selected claim target')
        span=spans[index]
        entry={'target':target,'content_revision_sha256':ref['content_revision_sha256'],
               'start':span['start'],'end':span['end'],'quote':text[span['start']:span['end']],
               'attribution':attribution}
        # Repeated identical highlight/target choices are stable, not duplicated evidence.
        ident=document_hash(entry)
        if ident not in seen:
            seen.add(ident);evidence.append(entry)
    details['evidence']=evidence
    annotation,selected,unassigned=_projection(obj['answers'],details,spans,text,ref['content_revision_sha256'])
    manifest={'schema_version':'aic-argilla-details-proposal-v1','submission_id':submission_id,
              'source':item['source'],'contract_sha256':item['contract_sha256'],
              'mapping_confirmation':True,'mapping_scope':'evidence targets only; not annotation approval',
              'mappings':mappings,'details':details,'annotation':annotation,
              'selected_span_indexes':selected,'unassigned_span_indexes':unassigned}
    target=Path(output)
    if target.exists():
        if read_object(target/'proposal.json') != manifest or (target/'details.json').read_bytes()!=encoded(details):
            raise ValueError('Existing details proposal differs; use a new output directory')
    else:
        publish_directory(target,{'proposal.json':encoded(manifest),'details.json':encoded(details)})
    return {'details_file':str(target/'details.json'),'selected_span_indexes':selected,
            'unassigned_span_indexes':unassigned,'state':'proposal_only_no_responses_written'}


def stage_existing_evidence(root, submission_id, *, repair_encoding=False):
    """Stage submitted target mappings unchanged; retain unused highlights in an audit.

This explicit path does not weaken the legacy all-highlights staging check. It
projects existing *targeted* evidence into Phase 2M, which has no native-highlight
field. It never assigns a target or attribution to an unassigned highlight.
"""
    context,obj,item,ref,text,spans=saved_response(root,submission_id,submitted=True)
    details=bridge.parse_details(obj['answers'].get('details'))
    changes=[]
    if repair_encoding:
        details,changes=repair_quote_encoding(details,spans,text,ref['content_revision_sha256'])
    annotation,selected,unassigned=_projection(obj['answers'],details,spans,text,ref['content_revision_sha256'])
    request={'schema_version':'aic-existing-evidence-projection-v1','submission_id':submission_id,
             'source':item['source'],'contract_sha256':item['contract_sha256'],
             'annotation':annotation,'selected_span_indexes':selected,'unassigned_span_indexes':unassigned,
             'annotation_changes':[], 'basis':'Existing submitted supplemental targets only; no new evidence meaning assigned'}
    if changes:
        request.update(schema_version='aic-existing-evidence-projection-v2',annotation_changes=changes,
                       basis='Existing submitted targets and exact saved highlights; reversible quote encoding repair only')
    ident='projection-'+document_hash(request)
    path=Path(root)/'evidence-projections'/ident
    if path.exists():
        receipt=read_object(path/'receipt.json')
        if receipt.get('request') != request:
            raise ValueError('Evidence projection receipt mismatch')
        draft=load_draft(context['store'],receipt['draft_id'])
        if draft['annotation']!=annotation or draft['source']!=item['source'] or draft['documents']!=bridge.contract()['documents']:
            raise ValueError('Projected draft binding mismatch')
    else:
        draft_id=create_draft(context['store'],item['source']['source_ref_id'],annotation)
        receipt={'request':request,'draft_id':draft_id,'state':'validated_draft_not_approved'}
        publish_directory(path,{'receipt.json':encoded(receipt)})
    return {'draft_id':receipt['draft_id'],'projection_id':ident,'state':receipt['state'],
            'annotation_changes':changes,'selected_span_indexes':selected,'unassigned_span_indexes':unassigned,
            'review_command':'python -m src.global_review review '+receipt['draft_id']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=bridge.DEFAULT_ROOT)
    commands=parser.add_subparsers(dest='command',required=True)
    projected=commands.add_parser('stage-existing')
    projected.add_argument('submission_id')
    projected.add_argument('--repair-quote-encoding',action='store_true',
                           help='Opt in to audited reversal of an exact UTF-8-as-CP1252 quote transcription; never changes targets or offsets')
    template=commands.add_parser('template')
    template.add_argument('--scope-note',required=True)
    template.add_argument('--output',type=Path,required=True)
    prepared=commands.add_parser('prepare')
    prepared.add_argument('submission_id')
    prepared.add_argument('--span-target',action='append',required=True,help='Saved zero-based span index=/claim/path; repeat for each human-selected mapping')
    prepared.add_argument('--attribution',required=True)
    prepared.add_argument('--output',type=Path,required=True)
    prepared.add_argument('--new-article-template',action='store_true')
    prepared.add_argument('--scope-note')
    prepared.add_argument('--confirm-evidence-mapping',action='store_true')
    args=parser.parse_args()
    try:
        if args.command=='stage-existing':
            result=stage_existing_evidence(args.root,args.submission_id,repair_encoding=args.repair_quote_encoding)
        elif args.command=='template':
            details=article_template(args.scope_note)
            publish_directory(args.output,{'details.json':encoded(details)})
            result={'details_file':str(args.output/'details.json'),'state':'unfilled_template_not_staging_ready'}
        else:
            mappings=[]
            for spec in args.span_target:
                index,target=spec.split('=',1)
                mappings.append({'span_index':int(index),'target':target})
            result=prepare_details(args.root,args.submission_id,mappings,args.attribution,args.output,
                confirm=args.confirm_evidence_mapping,new_article_template=args.new_article_template,scope_note=args.scope_note)
    except (OSError,ValueError,TypeError,KeyError) as exc:
        parser.exit(2,f'Evidence preparation rejected: {exc}\n')
    print(encoded(result).decode())


if __name__=='__main__':
    main()
