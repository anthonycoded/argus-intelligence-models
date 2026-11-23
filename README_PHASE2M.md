# Phase 2M: global intelligence annotation integration

AIC-1's global task is worldwide domain classification, starting with defense
versus nondefense and later multi-label defense event categorization. Topic
relevance is a separate optional task. This phase implements source registration
and human global review, not dataset export, splitting, model training or serving.

The preflight found the prior work uncommitted. With explicit user authorization,
the source-only baselines were committed as `4f1704d` (2J/2K) and `3399816` (2L).
The baseline suite passed all 182 tests before Phase 2M changes. No generated
artifacts were included in those commits. Phase 2M adds no dependency.

## Versioning and compatibility

- Archived `global_intelligence_v1.json`, its validator, the five legacy Taiwan
  annotations, and their provenance/rights and policy-review sidecars are unchanged.
- No relevance label is promoted, mapped or copied into a global annotation.
- New `global_intelligence_v2.json` retains the five multi-label domains and adds
  `defense_other` to the eight named defense event types. It covers evidenced
  defense developments outside the named categories, not uncertainty or mere
  military-themed reporting. Its gap must be explained by the reviewer.
- `policies/global_annotation_v1.json` is a separate, hashed review policy. It
  provides category inclusion/exclusion rules and the versioned local 249-code
  ISO alpha-2 vocabulary. Country codes include territories and are identifiers,
  not sovereignty assertions. Unknown/exceptional codes require a future registry
  version; `UK`, `XK`, `ZZ` and lowercase codes are not silently accepted.
- The new annotation schema is `aic-global-annotation-v2`. The older flat global
  template remains archival and cannot be approved by the new workflow.
- Phase 2L's manifests and trainer are unchanged and reject global envelopes.
  A future dataset/export contract must be implemented separately. Eligibility
  reports always set `training_ready` and `global_training_export_supported` false.

## Immutable content references

Default local store: `data/global_annotations/` (already ignored by Git).

```text
sources/src-<hash>/reference.json
sources/src-<hash>/content.utf8
sources/src-<hash>/provenance.json
drafts/draft-<hash>/draft.json
approvals/approval-<hash>/approval.json
rights/src-<hash>/rights-<hash>/decision.json
```

`aic-content-reference-v1` contains a canonical source URL, exact content revision
SHA-256, normalized duplicate fingerprint, publisher/title, publication metadata
(nullable normalized timestamp plus raw publisher value), collection timestamp,
representation type and provenance ID/hash. Input text is strict UTF-8, bounded
to 2 MiB, and copied byte-for-byte, including line endings and any BOM. Registration
does not strip, summarize or retrieve text. `content.utf8` is the representation
actually reviewed, which may be a permitted excerpt or a human summary rather
than a full original article. Do not claim source fidelity beyond that material.

Source-reference IDs depend on canonical URL and exact content hash. Re-registering
the same pair is refused. Case/whitespace variants have different exact revisions
but may share a normalized duplicate fingerprint. Metadata/provenance are immutable;
there is no in-place metadata correction command in this phase.

Every read validates metadata, source identity, content hash, duplicate fingerprint,
provenance identity and stored file hash. Drafts and approvals additionally bind the
exact reference-file hash. Changed or missing content/provenance is rejected.
Old content remains valid historical evidence when a NEW revision is registered;
the system does not assume which publication revision is current on the internet.

## CLI workflow

Global flags precede the subcommand. All operations are offline. Commands output
JSON identifiers; substitute the returned identifiers below. Templates require
manual completion and are deliberately invalid until filled out.

Register independently supplied, appropriately handled source content:

```powershell
python -m src.global_review register data/source_metadata.json --text-file data/permitted_content.txt
```

Use `examples/global_content_metadata_TEMPLATE.json` for the metadata structure.
The manual adapter accepts syntactically safe public-host HTTPS URLs worldwide,
but performs no network request or publisher authentication. Named adapters retain
their publisher allowlists: `navy` is restricted to navy.mil and `defensenews` to
the existing Defense News article allowlist. Manual registration is an explicit
local content assertion, not a downloader or an extension of either feed allowlist.

Prepare a source reference directly from either existing discovery adapter:

```powershell
python -m src.global_review prepare data/discovery/navy_batch_001.jsonl DISCOVERY_ID --adapter navy --text-file data/permitted_content.txt --content-type human_summary --rights-note "Accurate human-supplied handling statement; training rights unverified"
python -m src.global_review prepare data/discovery/defensenews_001.jsonl DISCOVERY_ID --adapter defensenews --text-file data/permitted_content.txt --content-type permitted_excerpt --rights-note "Accurate excerpt handling statement; training rights unverified"
```

Preparation checks exactly one matching discovery row, its canonical URL-derived
ID, unreviewed status, publisher identity and safe URL. Provenance retains discovery
file/row hashes. No body retrieval, access-control bypass, labeling or rights
clearance occurs. Discovery provenance records local identity, not remote truth.

Create, inspect and explicitly approve a draft:

```powershell
python -m src.global_review draft SOURCE_REF_ID data/global_article_review.json
python -m src.global_review review DRAFT_ID
python -m src.global_review approve DRAFT_ID --reviewer REVIEWER_ID --confirm-human-review
python -m src.global_review eligibility
python -m src.global_review history
```

The review command displays the bound draft and path to its exact source text.
Read both and the stored policy/category rules before confirming. A reviewer name
and confirmation flag are attestations, not authenticated proof of human review.
Drafts are immutable snapshots; revise the external annotation JSON and create a
new draft to correct an unapproved draft. Unapproved drafts are never eligible.

The article template is `examples/global_article_annotation_v2_TEMPLATE.json`.
For every label/entity/date/location and non-unknown evidence status, supply an
entry with a target path and exact source span:

```json
{
  "target": "/domains/0",
  "content_revision_sha256": "REPLACE-with-source-content-hash",
  "start": 0,
  "end": 20,
  "quote": "REPLACE-exact-span",
  "attribution": "REPLACE-with-source-attribution"
}
```

Offsets count Unicode characters in the exact decoded registered text, not bytes.
`quote` must equal `text[start:end]`; hashes, bounds, target paths and coverage
are validated. Targets are `/domains/N`, `/defense_event_types/N`, `/countries/N`
(the entire country/role pair), `/organizations/N`, `/event_date`,
`/event_location`, `/evidence_status`, or those fields under `/events/N`.
Rationale/unknown fields cannot serve as evidence targets. A valid quote proves
source grounding, NOT semantic entailment, independence or event truth. Reviewers
must verify that it actually supports the targeted claim, role and category.

`reported`, `disputed`, and `unknown` are supported evidence statuses. Independent
corroboration is intentionally refused until a multi-source corroboration contract
exists; a source claiming corroboration is not independently verified here.

## Article labels and event instances

Domains and defense event types are multi-label. `other` is exclusive of substantive
domains. Defense items need at least one event type; nondefense items have none.
`defense_other` cannot coexist with a named type on the same event instance.
Country roles distinguish mentioned countries from actors/hosts/targets/etc.
Unknown countries, dates or locations are omitted/null rather than guessed.

An article has its own aggregate fields and a separate `events` array. Each event
has `instance_id` plus domains, defense event types, countries, organizations,
date, location, evidence status and rationale. IDs are unique ONLY within the
article annotation, not stable global event IDs or leakage cluster IDs.

Choose `event_coverage` explicitly:

- `complete`: event label unions must account for every substantive article label.
- `partial`: at least one event and a scope/gap explanation are required.
- `not_enumerated`: no event instances; explain the article-only scope.

Event labels/entities must appear in the article aggregate. Different event dates
or locations require the corresponding article field to be null. Multi-event
articles can contain both defense and economic/diplomatic events without treating
all events as military. Entity mention does not automatically establish an actor.

## Approval envelopes and corrections

Approval envelopes contain a content-addressed approval ID, annotation family,
revision number, reviewer identity and UTC timestamp, explicit confirmation,
taxonomy version/hash, annotation-policy version/hash, exact content revision hash,
provenance binding, approved draft hash, and superseded approval ID. Full taxonomy
and policy snapshots are embedded for historical interpretation. Document hashes
use canonical JSON (UTF-8, sorted keys, compact separators); content/reference and
provenance hashes bind exact stored bytes.

Duplicate approvals/roots and forks are refused. Revisions must explicitly
supersede the current head of the SAME canonical article. Historical drafts and
approvals are retained and validated; no API overwrites them.

```powershell
python -m src.global_review revise APPROVAL_ID data/corrected_review.json
python -m src.global_review approve NEW_DRAFT_ID --reviewer REVIEWER_ID --confirm-human-review
```

To review changed article text, register a new content revision first and use
`revise ... --source-ref NEW_SOURCE_REF_ID`. Evidence must reference the new text.
Another article URL cannot be substituted into a revision chain. A changed current
taxonomy/policy rejects old pending drafts; historical approvals retain their
embedded snapshots. New versions must be issued rather than editing archives.

## Separate rights decisions and eligibility

Registration starts rights at `unverified`; annotation approval never changes it.
Rights decisions have separate reviewer confirmation, UTC time, basis, model-training
scope, representation type, and exact source/content/provenance binding. Example
of recording a restriction AFTER an actual rights review:

```powershell
python -m src.global_review rights SOURCE_REF_ID --status restricted --evidence "Documented restriction for the intended training use" --reviewer RIGHTS_REVIEWER_ID --confirm-rights-review
python -m src.global_review eligibility
```

`cleared` is available only as an explicit human attestation with a documented
basis. Public accessibility, official government origin, personal use, a summary,
or approval alone never establishes clearance. The tool is not a legal evaluator.
Missing/uncleared/restricted/stale rights block future-dataset eligibility; multiple
decisions create a conflict, never latest-wins. Do not delete decisions to bypass
restrictions. Reconciliation/revocation policy is a separately reviewed future task.

Only the current approval head for each canonical article can be a future dataset
candidate. Superseded revisions stay historical. Approval validity and rights status
are reported separately. Invalid approval history blocks all candidate eligibility.
Global envelopes are explicitly incompatible with the Phase 2L training manifest.

## Verification and limits

Tests use synthetic content in temporary directories and prohibit network calls.
They cover stale/missing sources, forged evidence, country/date/category rules,
both feed bridges, explicit confirmations, duplicates, revisions/history, rights,
CLI behavior and Phase 2L manifest rejection. No model is imported or trained.

This is a local, single-writer filesystem workflow. Immutable means append-only
application behavior with tamper detection, not filesystem WORM or signatures.
An actor able to forge/delete the entire authoritative store can forge/remove
history. Concurrent writers, hostile filesystems, reviewer authentication, semantic
entailment checks, publisher authentication, global event resolution, human
adjudication/rejection records and training export are not implemented here.
Content/metadata is sensitive research material: keep the entire generated store
out of Git. No Phase 2N dataset or classifier is created by this phase.
