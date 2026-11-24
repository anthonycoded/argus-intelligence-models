"""Local Argilla 2.8 staging adapter. Phase 2M remains the approval authority.

Single writer, append-only hashed bundles, no content retrieval, rights mutation,
model imports or inference. Argilla is a review UI, never a training input.
"""
import argparse
import json
import os
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import UUID

from .candidate_import import canonical_source
from .content_reference import check_binding, load_source
from .global_annotation_schema import validate_article
from .global_io import (digest, document_hash, encoded, identifier, keys, parse_json,
                        publish_directory, read_object, string)
from .global_review import (_documents, approve, create_draft, eligibility_report,
                            history, load_approval, load_draft)
from .global_sampling import load_sample, prepare_review

DEFAULT_ROOT = Path('data/argilla')
QUESTION_NAMES = {'domains', 'defense_event_types', 'rationale', 'event_coverage', 'details', 'evidence_spans'}
DETAIL_FIELDS = {'countries', 'organizations', 'event_date', 'event_location', 'evidence_status',
                 'event_coverage_note', 'events', 'evidence'}
PRESENTATION = 'aic-argilla-content-view-v1'


def _save(root, directory, obj, prefix):
    ident = prefix + document_hash(obj)
    target = Path(root) / directory / ident
    if target.exists():
        if read_object(target / 'data.json') != obj:
            raise ValueError('Immutable bridge artifact mismatch')
    else:
        publish_directory(target, {'data.json': encoded(obj)})
    return ident


def _read(root, directory, ident, prefix):
    identifier(ident, prefix)
    obj = read_object(Path(root) / directory / ident / 'data.json')
    if prefix + document_hash(obj) != ident:
        raise ValueError('Bridge artifact hash mismatch')
    return obj


def contract():
    return {'schema_version': 'aic-argilla-contract-v1', 'documents': _documents(),
            'questions': sorted(QUESTION_NAMES), 'defense_empty_choice': 'none'}


def _context(root):
    obj = read_object(Path(root) / 'context.json')
    keys(obj, {'sample', 'sample_manifest_sha256', 'store', 'contract'}, 'bridge context')
    if obj['contract'] != contract():
        raise ValueError('Stale taxonomy/policy/Argilla contract; use a new bridge root')
    if digest((Path(obj['sample']) / 'manifest.json').read_bytes()) != obj['sample_manifest_sha256']:
        raise ValueError('Sample binding changed')
    _, rows = load_sample(obj['sample'])
    return obj, rows


def records(root):
    context, rows = _context(root)
    candidates = {r['candidate_id']: r for r in rows}
    result = {}
    for path in sorted((Path(root) / 'records').glob('record-*/data.json')):
        ident = path.parent.name
        obj = _read(root, 'records', ident, 'record-')
        extra = {'presentation', 'prior_submissions'} if 'presentation' in obj else set()
        keys(obj, {'candidate', 'source', 'contract_sha256', 'supersedes', 'fields', 'metadata'} | extra, 'bridge record')
        row = obj['candidate']
        if candidates.get(row['candidate_id']) != row or obj['contract_sha256'] != document_hash(context['contract']):
            raise ValueError('Candidate/contract binding mismatch')
        if obj['source'] is not None:
            ref, text = check_binding(context['store'], obj['source'])
            _match_source(row, ref)
        else:
            text = 'PENDING CONTENT: metadata only. Draft labels are not evidence. Attach a permitted representation before AIC-1 review.'
        if extra:
            if obj['presentation'] != PRESENTATION or obj['source'] is None:
                raise ValueError('Unsupported content presentation')
            expected = _content_record(root, row, obj['source'], text, obj['supersedes'], obj['prior_submissions'])
        else:
            expected = _record(row, obj['source'], text, obj['supersedes'])
        if obj != expected:
            raise ValueError('Record fields/content/metadata mismatch')
        result[ident] = obj
    # Each candidate has a single append-only representation chain.
    children, heads = set(), {}
    for ident, obj in result.items():
        previous = obj['supersedes']
        candidate = obj['candidate']['candidate_id']
        if previous:
            if previous not in result or previous in children or result[previous]['candidate']['candidate_id'] != candidate:
                raise ValueError('Invalid representation history')
            children.add(previous)
        else:
            if candidate in heads:
                raise ValueError('Duplicate representation root')
            heads[candidate] = ident
    for candidate in candidates:
        tips = [i for i, r in result.items() if r['candidate']['candidate_id'] == candidate and i not in children]
        if len(tips) != 1 or candidate not in heads:
            raise ValueError('Missing or conflicting representation head')
        # Verify reachability; disallow disconnected cycles.
        seen, cursor = set(), tips[0]
        while cursor is not None:
            if cursor in seen:
                raise ValueError('Representation cycle')
            seen.add(cursor)
            cursor = result[cursor]['supersedes']
        if len(seen) != sum(r['candidate']['candidate_id'] == candidate for r in result.values()):
            raise ValueError('Disconnected representation history')
        heads[candidate] = tips[0]
    return context, result, heads


def _match_source(row, ref):
    if ref['canonical_source_id'] != canonical_source(row['source_id']):
        raise ValueError('Source identity mismatch')
    for name in ('article_title', 'publisher', 'collected_at', 'published_at', 'published_at_raw'):
        if ref['metadata'][name] != row.get(name):
            raise ValueError('Source metadata mismatch: ' + name)


def _record(row, binding, text, supersedes=None):
    c = contract()
    metadata = {'candidate_id': row['candidate_id'], 'state': 'pending_content' if binding is None else 'content_attached',
                'content_revision': binding['content_revision_sha256'] if binding else 'none'}
    context = {'source_url': row['source_id'], 'publisher': row['publisher'],
               'published_at': row.get('published_at'), 'published_at_raw': row.get('published_at_raw'),
               'collected_at': row['collected_at'], 'candidate_id': row['candidate_id'],
               'sampling': row['sampling'], 'source_binding': binding,
               'taxonomy_version': c['documents']['taxonomy']['version'],
               'taxonomy_sha256': document_hash(c['documents']['taxonomy']),
               'policy_sha256': document_hash(c['documents']['policy']),
               'rights': 'Separate AIC-1 decision; attachment and submission grant no rights.'}
    fields = {'title': row['article_title'], 'source': row['source_id'],
              'context': encoded(context).decode(), 'text': text,
              'guidance': guidance(c)}
    return {'candidate': row, 'source': binding, 'contract_sha256': document_hash(c),
            'supersedes': supersedes, 'fields': fields, 'metadata': metadata}


def _content_record(root, row, binding, text, supersedes, prior_submissions):
    """New representations only: archived Phase 2P records remain byte-identical."""
    obj = _record(row, binding, text, supersedes)
    context, _ = _context(root)
    ref, _, actual = load_source(context['store'], binding['source_ref_id'])
    if binding != actual or not isinstance(prior_submissions, list) or len(set(prior_submissions)) != len(prior_submissions):
        raise ValueError('Invalid content view binding/history')
    kind = ref['metadata']['content_type']
    lines = ['CONTENT ATTACHED — RE-REVIEW REQUIRED',
             'Representation: ' + kind + (' (reviewer-authored summary; not full article text)' if kind == 'human_summary' else ''),
             'Publisher: ' + row['publisher'],
             'Published: ' + str(row.get('published_at') or row.get('published_at_raw') or 'unknown'),
             'Collected: ' + row['collected_at'],
             'Handling basis: ' + ref['metadata']['rights_note'],
             'Training rights: separate AIC-1 decision; attachment does not clear rights.',
             'Source reference: ' + binding['source_ref_id'],
             'Content SHA-256: ' + ref['content_revision_sha256'],
             'Provenance ID: ' + ref['provenance_id'],
             'Previous record (retained): ' + str(supersedes),
             'Prior choices below remain on the original record. Re-select only after reading this representation.']
    for ident in prior_submissions:
        previous = _read(root, 'submissions', ident, 'submission-')
        if previous['record_id'] != supersedes or previous['status'] != 'draft':
            raise ValueError('Prior draft snapshot does not belong to the previous record')
        lines += ['Prior draft author UUID: ' + previous['reviewer_id'],
                  'Prior draft answers (not current labels/evidence): ' + encoded(previous['answers']).decode()]
    obj['fields']['source'] = '[Open original publisher source](<' + quote(row['source_id'], safe=':/?&=%@+;,-._~') + '>)'
    obj['fields']['context'] = '\n\n'.join(lines)
    obj['fields']['guidance'] = ('Highlight support in the exact text. Use evidence CLI to map native spans to '
        'AIC-1 Unicode offsets and UTF-8 byte ranges. Do not carry evidence across revisions. '
        'The displayed representation may be a summary or excerpt, not the complete publisher article.\n\n' + obj['fields']['guidance'])
    obj.update(presentation=PRESENTATION, prior_submissions=prior_submissions)
    return obj


def guidance(c):
    return ('Global article labels are separate from article-local event instances. Other is exclusive. '
            'Choose none for no defense events. Similarity/query hints are unverified, never labels. '
            'Save incomplete work as DRAFT. Submitted does not mean approved. '
            'Stage 2: details is a JSON object with exactly countries, organizations, event_date, '
            'event_location, evidence_status, event_coverage_note, events, evidence. '
            'Use null/empty arrays for genuinely unknown/absent information, not invented values. '
            'Evidence must target each claim and match exact text Unicode offsets and content hash. '
            'See README_PHASE2P.md for the supplemental form and approval boundary.\n' +
            encoded(c['documents']).decode())


def initialize(root, sample, store):
    manifest, rows = load_sample(sample)
    context = {'sample': str(Path(sample).resolve()), 'sample_manifest_sha256': digest((Path(sample)/'manifest.json').read_bytes()),
               'store': str(Path(store).resolve()), 'contract': contract()}
    root = Path(root)
    if (root / 'context.json').exists():
        if read_object(root / 'context.json') != context:
            raise ValueError('Bridge already bound to a different sample/store/contract')
        records(root)
    else:
        if root.exists():
            raise ValueError('New bridge root required')
        files = {'context.json': encoded(context)}
        publish_directory(root, files)
        for row in rows:
            obj = _record(row, None, 'PENDING CONTENT: metadata only. Draft labels are not evidence. Attach a permitted representation before AIC-1 review.')
            _save(root, 'records', obj, 'record-')
    return {'candidates': len(rows), 'dataset_name': dataset_name()}


def dataset_name():
    return 'aic-global-v2-' + document_hash(contract())[:12]


def attach(root, candidate_id, text_file, content_type, rights_note, *, content_view=False):
    context, all_records, heads = records(root)
    if candidate_id not in heads:
        raise ValueError('Unknown candidate')
    previous = heads[candidate_id]
    row = all_records[previous]['candidate']
    string(rights_note, 'explicit handling basis')
    # Never infer authorship/permission from file presence or representation choice.
    raw = Path(text_file).read_bytes()
    if not raw or len(raw) > 2*1024*1024 or not raw.decode('utf-8').strip():
        raise ValueError('Content must be nonempty permitted UTF-8 text, at most 2 MiB')
    ident = 'src-' + document_hash([canonical_source(row['source_id']), digest(raw)])
    if not (Path(context['store']) / 'sources' / ident).exists():
        ident = prepare_review(context['sample'], candidate_id, Path(context['store']), text_file, content_type, rights_note)['source_ref_id']
    ref, text, binding = load_source(context['store'], ident)
    _match_source(row, ref)
    if ref['metadata']['content_type'] != content_type or ref['metadata']['rights_note'] != rights_note:
        raise ValueError('Existing representation has a different handling assertion')
    if all_records[previous]['source'] == binding:
        return previous
    if any(r['source'] == binding for r in all_records.values()):
        raise ValueError('Cannot restore a superseded representation as current')
    if content_view:
        _, snapshot = _export_head(root)
        prior = [] if snapshot is None else [ident for ident in snapshot['submissions']
            if (lambda s: s['record_id'] == previous and s['status'] == 'draft')(_read(root, 'submissions', ident, 'submission-'))]
        obj = _content_record(root, row, binding, text, previous, prior)
    else:
        obj = _record(row, binding, text, previous)
    return _save(root, 'records', obj, 'record-')


def settings(rg, readable=False):
    c = contract()
    tax = c['documents']['taxonomy']
    return rg.Settings(guidelines=guidance(c),
        fields=[rg.TextField(name=n, use_markdown=readable and n == 'source',
                **({'title': {'title':'Article title', 'source':'Original publisher link',
                              'context':'Source, provenance and prior draft', 'text':'Registered content — exact representation',
                              'guidance':'Annotation guidance'}[n]} if readable else {}))
                for n in ('title', 'source', 'context', 'text', 'guidance')],
        questions=[rg.MultiLabelQuestion(name='domains', labels=tax['domains']),
                   rg.MultiLabelQuestion(name='defense_event_types', labels=tax['defense_event_types']+['none']),
                   rg.TextQuestion(name='rationale'),
                   rg.LabelQuestion(name='event_coverage', labels=['not_enumerated', 'partial', 'complete']),
                   rg.TextQuestion(name='details', description='Stage 2 supplemental JSON; see guidance. Save draft until complete.'),
                   rg.SpanQuestion(name='evidence_spans', field='text', labels=['support'], required=False)],
        metadata=[rg.TermsMetadataProperty(name=n) for n in ('candidate_id', 'state', 'content_revision')])


def local_client(url=None):
    url = url or os.environ.get('ARGILLA_API_URL', 'http://127.0.0.1:6900')
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('Only local http://127.0.0.1:PORT Argilla servers are supported')
    key = os.environ.get('ARGILLA_API_KEY')
    string(key, 'ARGILLA_API_KEY')
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    import argilla as rg
    return rg, rg.Argilla(api_url=url, api_key=key, trust_env=False, follow_redirects=False)


def _settings_signature(value):
    if isinstance(value, dict):
        return {k: _settings_signature(v) for k, v in value.items()
                if k not in {'id', 'inserted_at', 'updated_at', 'dataset_id'} and v is not None}
    if isinstance(value, list):
        return [_settings_signature(v) for v in value]
    return value


def setup(rg, client, workspace='aic1'):
    expected = settings(rg)
    dataset = client.datasets(name=dataset_name(), workspace=workspace)
    if dataset is None:
        dataset = rg.Dataset(name=dataset_name(), workspace=workspace, settings=expected, client=client).create()
    # Persisted contract in fields is checked on every import/export as well.
    if _settings_signature(dataset.settings.serialize()) not in [
            _settings_signature(expected.serialize()), _settings_signature(settings(rg, True).serialize())]:
        raise ValueError('Existing Argilla dataset settings mismatch')
    return dataset


def improve_ui(rg, dataset):
    """Only field presentation changes; retain field/question IDs and all responses."""
    expected = settings(rg, True)
    for field in expected.fields:
        current = dataset.settings.fields[field.name]
        current.title = field.title
        current.use_markdown = field.use_markdown
        current.update()
    dataset.settings.get()
    if _settings_signature(dataset.settings.serialize()) != _settings_signature(expected.serialize()):
        raise ValueError('Readable field settings update mismatch')
    return {'dataset': dataset.name, 'field_presentation': 'readable', 'responses_modified': False}


def attach_and_sync(root, dataset, rg, client, candidate_id, text_file, content_type, rights_note):
    # Snapshot actual drafts first, without editing responses. Failure stops attachment.
    export_responses(root, dataset, client)
    record_id = attach(root, candidate_id, text_file, content_type, rights_note, content_view=True)
    result = import_records(root, dataset, rg)
    result.update(record_id=record_id, candidate_id=candidate_id, re_review_required=True,
                  prior_draft_preserved=True)
    return result


def import_records(root, dataset, rg):
    _, items, _ = records(root)
    remote = {}
    for record in dataset.records:
        if record.id in remote:
            raise ValueError('Duplicate Argilla external ID')
        remote[record.id] = record
    added = 0
    for ident, item in items.items():
        existing = remote.get(ident)
        if existing is not None:
            _verify_remote(existing, ident, item)
            continue
        dataset.records.log([rg.Record(id=ident, fields=item['fields'], metadata=item['metadata'])])
        added += 1
    return {'added': added, 'total_representations': len(items)}


def _verify_remote(record, ident, item):
    if record.id != ident or record.fields.to_dict() != item['fields'] or record.metadata.to_dict() != item['metadata']:
        raise ValueError('Argilla record binding/content/metadata mismatch')


def export_responses(root, dataset, client):
    _, items, _ = records(root)
    exported = []
    for record in dataset.records:
        ident = record.id
        if ident not in items:
            raise ValueError('Unknown Argilla record')
        _verify_remote(record, ident, items[ident])
        grouped = {}
        for name in {answer.question_name for answer in record.responses}:
            responses = record.responses[name]
            if name not in QUESTION_NAMES:
                raise ValueError('Unknown response question')
            for answer in responses:
                user = str(UUID(str(answer.user_id)))
                status = getattr(answer.status, 'value', answer.status)
                if status not in {'draft', 'submitted', 'discarded'}:
                    raise ValueError('Unknown response status')
                entry = grouped.setdefault(user, {'status': status, 'answers': {}})
                if entry['status'] != status or name in entry['answers']:
                    raise ValueError('Mixed statuses/duplicate reviewer answers')
                entry['answers'][name] = answer.value
        for user, group in grouped.items():
            actual = client.users(id=user)
            if actual is None or str(actual.id) != user:
                raise ValueError('Unknown Argilla reviewer identity')
            string(actual.username, 'Argilla reviewer username')
            obj = {'schema_version': 'aic-argilla-submission-v1', 'record_id': ident,
                   'reviewer_id': user, 'reviewer_username': actual.username, **group}
            exported.append(_save(root, 'submissions', obj, 'submission-'))
    exported.sort()
    previous, snapshot = _export_head(root)
    if snapshot is not None and snapshot['submissions'] == exported:
        export_id = previous
    else:
        export_id = _save(root, 'exports', {'submissions': exported, 'supersedes': previous}, 'export-')
    return {'submissions': exported, 'count': len(exported), 'export_id': export_id}


def _export_head(root):
    snapshots = {p.parent.name: _read(root, 'exports', p.parent.name, 'export-')
                 for p in (Path(root)/'exports').glob('export-*/data.json')}
    if not snapshots:
        return None, None
    parents = []
    for snapshot in snapshots.values():
        keys(snapshot, {'submissions', 'supersedes'}, 'response export snapshot')
        if not isinstance(snapshot['submissions'], list) or len(set(snapshot['submissions'])) != len(snapshot['submissions']):
            raise ValueError('Malformed response membership')
        for ident in snapshot['submissions']:
            _read(root, 'submissions', ident, 'submission-')
        if snapshot['supersedes'] is not None:
            if snapshot['supersedes'] not in snapshots:
                raise ValueError('Missing export history')
            parents.append(snapshot['supersedes'])
    tips = set(snapshots)-set(parents)
    if len(tips) != 1 or len(set(parents)) != len(parents):
        raise ValueError('Conflicting export history')
    tip = next(iter(tips))
    seen, cursor = set(), tip
    while cursor is not None:
        if cursor in seen:
            raise ValueError('Export history cycle')
        seen.add(cursor)
        cursor = snapshots[cursor]['supersedes']
    if seen != set(snapshots):
        raise ValueError('Disconnected export history')
    return tip, snapshots[tip]


def _submission(root, ident):
    context, items, heads = records(root)
    obj = _read(root, 'submissions', ident, 'submission-')
    _, snapshot = _export_head(root)
    if snapshot is None or ident not in snapshot['submissions']:
        raise ValueError('Stale/withdrawn submission; export current responses again')
    keys(obj, {'schema_version', 'record_id', 'reviewer_id', 'reviewer_username', 'status', 'answers'}, 'submission')
    if obj['schema_version'] != 'aic-argilla-submission-v1':
        raise ValueError('Unknown submission schema')
    UUID(obj['reviewer_id'])
    string(obj['reviewer_username'], 'reviewer username')
    if obj['status'] != 'submitted':
        raise ValueError('Only submitted responses may be staged')
    item = items.get(obj['record_id'])
    if item is None or heads[item['candidate']['candidate_id']] != obj['record_id']:
        raise ValueError('Stale or unknown representation')
    if item['source'] is None:
        raise ValueError('Pending content cannot be staged')
    ref, text = check_binding(context['store'], item['source'])
    answers = obj['answers']
    if item.get('presentation') == PRESENTATION:
        answers = deepcopy(answers)
        answers['evidence_spans'] = normalized_spans(text, answers.get('evidence_spans', []))
    annotation = map_answers(answers, text, ref['content_revision_sha256'])
    return context, obj, item, annotation


def span_offsets(text, start, end, unit='utf16'):
    """Explicit half-open coordinates: browser UTF-16 -> Python Unicode -> UTF-8."""
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError('Invalid evidence span range')
    if unit == 'utf16':
        boundaries, offset = {0:0}, 0
        for index, char in enumerate(text, 1):
            offset += len(char.encode('utf-16-le'))//2
            boundaries[offset] = index
        if start not in boundaries or end not in boundaries:
            raise ValueError('Span exceeds content or splits a UTF-16 surrogate pair')
        start, end = boundaries[start], boundaries[end]
    elif unit != 'codepoint':
        raise ValueError('Unknown span coordinate unit')
    if end > len(text):
        raise ValueError('Evidence span exceeds registered text')
    return {'start':start, 'end':end, 'quote':text[start:end],
            'utf8_byte_start':len(text[:start].encode('utf-8')),
            'utf8_byte_end':len(text[:end].encode('utf-8'))}


def normalized_spans(text, spans):
    if not isinstance(spans, list):
        raise ValueError('Malformed native span collection')
    result = []
    for span in spans:
        keys(span, {'start','end','label'}, 'native evidence span')
        if span['label'] != 'support':
            raise ValueError('Unknown native evidence label')
        converted = span_offsets(text, span['start'], span['end'])
        result.append({k:converted[k] for k in ('start','end')} | {'label':span['label']})
    return result


def evidence_from_span(root, submission_id, span_index, target, attribution):
    """Map a real saved human highlight; no label, attribution or span is inferred."""
    context, items, heads = records(root)
    obj = _read(root, 'submissions', submission_id, 'submission-')
    _, snapshot = _export_head(root)
    if snapshot is None or submission_id not in snapshot['submissions']:
        raise ValueError('Stale/withdrawn response; export current responses')
    item = items.get(obj['record_id'])
    if item is None or heads[item['candidate']['candidate_id']] != obj['record_id']:
        raise ValueError('Stale representation; re-highlight current registered content')
    if item['source'] is None:
        raise ValueError('Pending/empty content cannot supply evidence')
    if obj['status'] not in {'draft', 'submitted'}:
        raise ValueError('Discarded responses cannot supply evidence')
    ref, text = check_binding(context['store'], item['source'])
    spans = obj['answers'].get('evidence_spans', [])
    if not isinstance(spans, list) or type(span_index) is not int or not 0 <= span_index < len(spans):
        raise ValueError('Select an existing saved evidence span index')
    span = spans[span_index]
    keys(span, {'start','end','label'}, 'native evidence span')
    if span['label'] != 'support':
        raise ValueError('Unknown native span label')
    string(target, 'human-selected evidence target')
    string(attribution, 'human-supplied attribution')
    converted = span_offsets(text, span['start'], span['end'])
    evidence = {'target':target,'content_revision_sha256':ref['content_revision_sha256'],
                **{k:converted[k] for k in ('start','end','quote')},'attribution':attribution}
    return {'record_id':obj['record_id'], 'reviewer_id':obj['reviewer_id'],
            'native_offset_unit':'utf16', 'evidence':evidence,
            'utf8_byte_range':{'start':converted['utf8_byte_start'],'end':converted['utf8_byte_end']},
            'note':'Mapping only; the reviewer must check target, source support and complete annotation validity.'}


def map_answers(answers, text, revision):
    if not isinstance(answers, dict):
        raise ValueError('Incomplete/unknown response fields: expected question answers as an object')
    missing = sorted((QUESTION_NAMES-{'evidence_spans'})-set(answers))
    if missing:
        raise ValueError('Incomplete/unknown response fields: complete these Argilla questions: ' + ', '.join(missing))
    if set(answers)-QUESTION_NAMES:
        raise ValueError('Incomplete/unknown response fields: remove unsupported response questions')
    details = parse_details(answers['details'])
    types = answers['defense_event_types']
    if not isinstance(types, list) or not types or ('none' in types and types != ['none']):
        raise ValueError('Select explicit none or defense categories, exclusively')
    annotation = {'schema_version': 'aic-global-annotation-v2', 'domains': answers['domains'],
                  'defense_event_types': [] if types == ['none'] else types,
                  'rationale': answers['rationale'], 'event_coverage': answers['event_coverage'], **details}
    if answers['event_coverage'] == 'partial' and not details['events']:
        raise ValueError('event_coverage: partial requires at least one instance in details.events. '
                         'For article-level annotation without enumerated events, select not_enumerated '
                         'and explain the scope in details.event_coverage_note; do not invent events.')
    if not details['evidence']:
        raise ValueError('details.evidence: nonempty source-grounded evidence required, including support for '
                         'each selected domain. Highlight the registered text, save and export the response, '
                         'then use argilla_bridge evidence to map the span to a claim target. '
                         'Native highlights alone do not replace supplemental evidence.')
    c = contract()['documents']
    validate_article(annotation, c['taxonomy'], c['policy'], text, revision)
    spans = answers.get('evidence_spans', [])
    if not isinstance(spans, list):
        raise ValueError('Malformed native evidence spans')
    for span in spans:
        keys(span, {'start', 'end', 'label'}, 'native evidence span')
        if (type(span['start']) is not int or type(span['end']) is not int or span['label'] != 'support'
                or not any((e['start'], e['end']) == (span['start'], span['end']) for e in annotation['evidence'])):
            raise ValueError('Native span must correspond to validated supplemental evidence')
    return annotation


def parse_details(value):
    """Actionable supplemental-form errors without echoing annotation text or keys."""
    guide = 'Complete the structured form in examples/argilla_details_TEMPLATE.json and paste one JSON object into Argilla details.'
    if not isinstance(value, str):
        raise ValueError('details: expected JSON object text. ' + guide)
    if not value.strip():
        raise ValueError('details: empty or whitespace-only. ' + guide)
    try:
        details = parse_json(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f'details: invalid JSON at line {exc.lineno}, column {exc.colno}. '
                         'Prose and Markdown code fences are not JSON; use double-quoted field names. ' + guide) from None
    except ValueError:
        raise ValueError('details: invalid JSON; duplicate keys and non-finite numbers are forbidden. ' + guide) from None
    if not isinstance(details, dict):
        raise ValueError('details: expected one JSON object, not a list, scalar or null. ' + guide)
    missing = sorted(DETAIL_FIELDS-set(details))
    unexpected = len(set(details)-DETAIL_FIELDS)
    if missing or unexpected:
        reason = (' Missing required fields: ' + ', '.join(missing) + '.') if missing else ''
        if unexpected:
            reason += f' Remove {unexpected} unexpected field(s).'
        raise ValueError('details: supplemental form fields do not match the schema.' + reason + ' ' + guide)
    for field in ('countries','organizations','events','evidence'):
        if not isinstance(details[field], list):
            raise ValueError('details.' + field + ': expected a JSON array; use [] only when the schema permits no entries.')
    return details


def stage(root, submission_id, supersedes=None):
    context, obj, item, annotation = _submission(root, submission_id)
    stage_obj = {'submission_id': submission_id, 'supersedes': supersedes}
    stage_id = 'stage-' + document_hash(stage_obj)
    path = Path(root) / 'stages' / stage_id
    if path.exists():
        receipt = read_object(path/'data.json')
        keys(receipt, {'request', 'draft_id', 'reviewer_id', 'reviewer_username', 'state'}, 'staging receipt')
        draft = load_draft(context['store'], receipt['draft_id'])
        if (receipt['request'] != stage_obj or receipt['reviewer_id'] != obj['reviewer_id']
                or receipt['reviewer_username'] != obj['reviewer_username'] or receipt['state'] != 'validated_draft'
                or draft['annotation'] != annotation or draft['source'] != item['source'] or draft['supersedes'] != supersedes):
            raise ValueError('Staging receipt mismatch')
        return receipt
    draft = create_draft(context['store'], item['source']['source_ref_id'], annotation, supersedes=supersedes)
    receipt = {'request': stage_obj, 'draft_id': draft, 'reviewer_id': obj['reviewer_id'],
               'reviewer_username': obj['reviewer_username'], 'state': 'validated_draft'}
    publish_directory(path, {'data.json': encoded(receipt)})
    return receipt


def review(root, submission_id, reviewer, confirm=False, supersedes=None):
    if confirm is not True:
        raise ValueError('Explicit --confirm-review required after inspecting content and draft')
    _, obj, _, _ = _submission(root, submission_id)
    if str(UUID(reviewer)) != obj['reviewer_id']:
        raise ValueError('Reviewer attribution mismatch; adjudication requires a separate response')
    receipt = stage(root, submission_id, supersedes)
    return _save(root, 'reviews', {'submission_id': submission_id, 'receipt': receipt, 'reviewer_id': reviewer,
                                  'confirmed': True}, 'review-')


def approve_review(root, review_id, reviewer, confirm=False):
    if confirm is not True:
        raise ValueError('Explicit --confirm-human-review required')
    receipt = _read(root, 'reviews', review_id, 'review-')
    if receipt['reviewer_id'] != reviewer or receipt['confirmed'] is not True:
        raise ValueError('Reviewer confirmation mismatch')
    context, submission, _, _ = _submission(root, receipt['submission_id'])
    expected = stage(root, receipt['submission_id'], receipt['receipt']['request']['supersedes'])
    if receipt['receipt'] != expected or reviewer != submission['reviewer_id']:
        raise ValueError('Review/submission mismatch')
    identity = 'argilla:' + reviewer + ':' + submission['reviewer_username']
    approvals, _ = history(context['store'])
    for approval in approvals.values():
        if approval['draft_id'] == expected['draft_id']:
            if approval['reviewed_by'] != identity:
                raise ValueError('Previously approved by another identity')
            return approval['approval_id']
    return approve(context['store'], expected['draft_id'], identity, True)


def reconcile(root):
    context, items, heads = records(root)
    approvals, _ = history(context['store'])
    rows = []
    for path in sorted((Path(root)/'submissions').glob('submission-*/data.json')):
        ident = path.parent.name
        submission = _read(root, 'submissions', ident, 'submission-')
        row = {'submission_id': ident, 'argilla_status': submission['status'], 'aic_state': 'unstaged',
               'reviewer_id': submission['reviewer_id']}
        try:
            _submission(root, ident)
            for stage_path in (Path(root)/'stages').glob('stage-*/data.json'):
                receipt = read_object(stage_path)
                if receipt['request']['submission_id'] == ident:
                    if stage_path.parent.name != 'stage-' + document_hash(receipt['request']):
                        raise ValueError('Staging receipt identity mismatch')
                    if stage(root, ident, receipt['request']['supersedes']) != receipt:
                        raise ValueError('Staging receipt validation mismatch')
                    load_draft(context['store'], receipt['draft_id'])
                    row.update(aic_state='validated_draft', draft_id=receipt['draft_id'])
                    for review_path in (Path(root)/'reviews').glob('review-*/data.json'):
                        reviewed = _read(root, 'reviews', review_path.parent.name, 'review-')
                        if reviewed['receipt'] == receipt:
                            row['aic_state'] = 'reviewed'
                    for approval in approvals.values():
                        if approval['draft_id'] == receipt['draft_id']:
                            row.update(aic_state='approved', approval_id=approval['approval_id'])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            row['blocked'] = str(exc)
        rows.append(row)
    return {'candidates': len(heads), 'representations': len(items), 'submissions': rows,
            'eligibility': eligibility_report(context['store'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--sample', type=Path, required=True)
    init.add_argument('--store', type=Path, default=Path('data/global_annotations'))
    attachment = commands.add_parser('attach')
    attachment.add_argument('--candidate-id', required=True)
    attachment.add_argument('--text-file', type=Path, required=True)
    attachment.add_argument('--content-type', required=True)
    attachment.add_argument('--rights-note', required=True)
    for name in ('setup', 'import', 'export', 'improve-ui', 'attach-sync'):
        remote = commands.add_parser(name)
        remote.add_argument('--workspace', default='aic1')
        if name == 'attach-sync':
            remote.add_argument('--candidate-id', required=True)
            remote.add_argument('--text-file', type=Path, required=True)
            remote.add_argument('--content-type', required=True)
            remote.add_argument('--rights-note', required=True)
    evidence = commands.add_parser('evidence')
    evidence.add_argument('submission_id')
    evidence.add_argument('--span-index', type=int, required=True)
    evidence.add_argument('--target', required=True)
    evidence.add_argument('--attribution', required=True)
    staging = commands.add_parser('stage')
    staging.add_argument('submission_id')
    staging.add_argument('--supersedes')
    reviewed = commands.add_parser('review')
    reviewed.add_argument('submission_id')
    reviewed.add_argument('--reviewer', required=True)
    reviewed.add_argument('--confirm-review', action='store_true')
    reviewed.add_argument('--supersedes')
    approval = commands.add_parser('approve')
    approval.add_argument('review_id')
    approval.add_argument('--reviewer', required=True)
    approval.add_argument('--confirm-human-review', action='store_true')
    commands.add_parser('reconcile')
    args = parser.parse_args()
    try:
        if args.command == 'init':
            result = initialize(args.root, args.sample, args.store)
        elif args.command == 'attach':
            result = {'record_id': attach(args.root, args.candidate_id, args.text_file, args.content_type, args.rights_note, content_view=True)}
        elif args.command in {'setup', 'import', 'export', 'improve-ui', 'attach-sync'}:
            _context(args.root)
            rg, client = local_client()
            dataset = setup(rg, client, args.workspace)
            if args.command == 'improve-ui':
                result = improve_ui(rg, dataset)
            elif args.command == 'attach-sync':
                result = attach_and_sync(args.root, dataset, rg, client, args.candidate_id, args.text_file, args.content_type, args.rights_note)
            else:
                result = {'dataset': dataset.name} if args.command == 'setup' else (
                    import_records(args.root, dataset, rg) if args.command == 'import' else export_responses(args.root, dataset, client))
        elif args.command == 'evidence':
            result = evidence_from_span(args.root, args.submission_id, args.span_index, args.target, args.attribution)
        elif args.command == 'stage':
            result = stage(args.root, args.submission_id, args.supersedes)
        elif args.command == 'review':
            result = {'review_id': review(args.root, args.submission_id, args.reviewer, args.confirm_review, args.supersedes)}
        elif args.command == 'approve':
            result = {'approval_id': approve_review(args.root, args.review_id, args.reviewer, args.confirm_human_review)}
        else:
            result = reconcile(args.root)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f'Argilla bridge rejected: {exc}\n')
    print(encoded(result).decode())


if __name__ == '__main__':
    main()
