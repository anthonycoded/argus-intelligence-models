"""Local Argilla 2.8 staging adapter. Phase 2M remains the approval authority.

Single writer, append-only hashed bundles, no content retrieval, rights mutation,
model imports or inference. Argilla is a review UI, never a training input.
"""
import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit
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
        keys(obj, {'candidate', 'source', 'contract_sha256', 'supersedes', 'fields', 'metadata'}, 'bridge record')
        row = obj['candidate']
        if candidates.get(row['candidate_id']) != row or obj['contract_sha256'] != document_hash(context['contract']):
            raise ValueError('Candidate/contract binding mismatch')
        if obj['source'] is not None:
            ref, text = check_binding(context['store'], obj['source'])
            _match_source(row, ref)
        else:
            text = 'PENDING CONTENT: metadata only. Draft labels are not evidence. Attach a permitted representation before AIC-1 review.'
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


def attach(root, candidate_id, text_file, content_type, rights_note):
    context, all_records, heads = records(root)
    if candidate_id not in heads:
        raise ValueError('Unknown candidate')
    previous = heads[candidate_id]
    row = all_records[previous]['candidate']
    string(rights_note, 'explicit handling basis')
    # Never infer authorship/permission from file presence or representation choice.
    raw = Path(text_file).read_bytes()
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
    return _save(root, 'records', _record(row, binding, text, previous), 'record-')


def settings(rg):
    c = contract()
    tax = c['documents']['taxonomy']
    return rg.Settings(guidelines=guidance(c),
        fields=[rg.TextField(name=n, use_markdown=False) for n in ('title', 'source', 'context', 'text', 'guidance')],
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
    if _settings_signature(dataset.settings.serialize()) != _settings_signature(expected.serialize()):
        raise ValueError('Existing Argilla dataset settings mismatch')
    return dataset


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
    annotation = map_answers(obj['answers'], text, ref['content_revision_sha256'])
    return context, obj, item, annotation


def map_answers(answers, text, revision):
    if not isinstance(answers, dict) or not QUESTION_NAMES-{'evidence_spans'} <= set(answers) or set(answers)-QUESTION_NAMES:
        raise ValueError('Incomplete/unknown response fields')
    details = parse_json(answers['details'])
    keys(details, DETAIL_FIELDS, 'supplemental article/event form')
    types = answers['defense_event_types']
    if not isinstance(types, list) or not types or ('none' in types and types != ['none']):
        raise ValueError('Select explicit none or defense categories, exclusively')
    annotation = {'schema_version': 'aic-global-annotation-v2', 'domains': answers['domains'],
                  'defense_event_types': [] if types == ['none'] else types,
                  'rationale': answers['rationale'], 'event_coverage': answers['event_coverage'], **details}
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
    for name in ('setup', 'import', 'export'):
        remote = commands.add_parser(name)
        remote.add_argument('--workspace', default='aic1')
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
            result = {'record_id': attach(args.root, args.candidate_id, args.text_file, args.content_type, args.rights_note)}
        elif args.command in {'setup', 'import', 'export'}:
            _context(args.root)
            rg, client = local_client()
            dataset = setup(rg, client, args.workspace)
            result = {'dataset': dataset.name} if args.command == 'setup' else (
                import_records(args.root, dataset, rg) if args.command == 'import' else export_responses(args.root, dataset, client))
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
