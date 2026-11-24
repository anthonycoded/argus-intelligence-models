# Phase 2P.1: readable source content and draft-preserving attachment

The existing Argilla 2.8 dataset and all 24 original records are retained. The first
SAnews draft was inspected and preserved: economics, none for defense events,
rationale, partial event coverage and free-form details. No response was moved,
rewritten, submitted or approved on the reviewer's behalf.

After the user confirmed that `review/001/content.txt` is a summary they wrote,
it was registered as **human_summary**, with training rights **unverified**, and
displayed as exact plain text in a new content-bearing record. It is not full
publisher article text. There are now **25 representations of 24 candidates**.
The new record displays the prior human draft choices as read-only context and
explicitly requests re-review; its answer controls start empty. The original draft
and all original record fields, metadata and server IDs were verified unchanged.

## Native Argilla features and compatibility

Verified SDK/server version: 2.8.0. Native `TextField` displays retained content;
`SpanQuestion` highlights the `text` field; metadata supports candidate/state/hash
filters. Markdown rendering on the separate source field supplies an explicit
publisher link. The source representation itself remains **plain text**, avoiding
Markdown transformations of evidence coordinates. All question names/types and
the existing dataset contract remain unchanged.

Native field configuration is updated through field resources, retaining question
IDs and responses. No documented native question provides the article-upload workflow
needed here; the local CLI supplies content instead. No second annotation app,
automatic retrieval or browser upload control was added.

Official references checked:

- [Native fields](https://docs.argilla.io/latest/reference/argilla/settings/fields/)
- [Native questions](https://docs.argilla.io/latest/reference/argilla/settings/questions/)
- [Records and responses](https://docs.argilla.io/latest/how_to_guides/record/)
- [Version-pinned native span implementation](https://github.com/argilla-io/argilla/blob/v2.8.0/argilla-frontend/components/features/annotation/container/fields/span-annotation/components/span-selection.ts)

## Simplest first-article workflow

From the repository root in PowerShell:

```powershell
. ./deploy/argilla/Use-LocalArgilla.ps1
# Field titles and source-link rendering only; safe to repeat.
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge improve-ui
# This exact attachment already succeeded; repeating it adds no records.
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge attach-sync --candidate-id candidate-04d4ab486c99ea5a3bcdb025058db8077ff2f86d6a9ad94bfed7357d1baaf5aa --text-file data/discovery/phase2o_001/review/001/content.txt --content-type human_summary --rights-note 'Reviewer-authored summary; user confirmed authorship for local annotation. Training rights unverified.'
```

Open **http://127.0.0.1:6900** and dataset `aic-global-v2-2c8eac532566`.
Filter metadata **state = content_attached** to find the first summary. Its current
record ID is:

```text
record-03423dca24a8ab0214be0b536adecf86b164ff9f666fc7190103dfcce10be7de
```

The content hash is
`5304b76b2de6741e84f0e359c72dff7f3323e601b4cf1eaf9f63a055ef33a020`.
The original metadata-only record and economics draft remain available separately.
Read the summary, its representation/handling/provenance context and prior choices.
Select economics/none again **only if that is your assessment after reading it**.
Do not reuse the old response as confirmed evidence on the new representation.

Review the event scope too: `partial` requires actual event instances and a gap
explanation. For an article-only annotation with no enumerated event instances,
choose `not_enumerated` and explain that scope. Do not invent events to satisfy it.
The old free-form details prose is retained in the prior draft, but the final
**details** question requires the structured form from
`examples/argilla_details_TEMPLATE.json`. Save unfinished work as a native draft.

## Attaching other authorized representations

Create a UTF-8 file containing only material you can legitimately retain. Use:

- `human_summary` only for a summary actually written by the reviewer;
- `permitted_excerpt` for an excerpt with an actual handling basis;
- another supported Phase 2M representation only when it accurately describes the text.

Do not use AI-generated prose as a human summary, paste restricted bodies, bypass
paywalls, or infer training rights from access. Replace every uppercase argument:

```powershell
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge attach-sync --candidate-id CANDIDATE_ID --text-file PATH_TO_AUTHORIZED_UTF8_FILE --content-type ACTUAL_CONTENT_TYPE --rights-note 'ACTUAL_HANDLING_BASIS; training rights unverified'
```

The command snapshots existing real responses, registers the exact permitted
representation and provenance, then imports only missing immutable records. The
returned `record_id` identifies the new representation. It never writes responses,
approvals or rights decisions. An identical attachment is idempotent; changed text
creates a new revision and requires re-review. Old drafts and evidence remain
historical. Unknown candidates, empty/whitespace text, invalid UTF-8, oversized text,
changed source bindings and inconsistent handling assertions are rejected.

Offline attachment remains available as `argilla_bridge attach` with the same four
arguments, followed by `argilla_bridge import` when the local server is available.
For prior-draft reminders, prefer `attach-sync`, which exports actual drafts first.

## Evidence without hand-counting offsets

1. Highlight the exact supporting phrase in the registered **text** field using
   the native **support** span label. Save the current content record as draft.
2. Export the saved native response:

```powershell
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge export
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge reconcile
```

3. Use the returned submission ID belonging to the current record/author. Span
   indexes are zero-based in that response's saved `evidence_spans` list. The original
   metadata draft has no supporting content and is refused. Example mapping for
   the first domain claim:

```powershell
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge evidence SUBMISSION_ID --span-index 0 --target /domains/0 --attribution 'Reviewer-authored summary of the linked SAnews report; verify support against this representation'
```

4. Inspect the returned quote. Copy **only the inner `evidence` object** into the
   supplemental form's evidence array, then complete all other required fields.
   The outer diagnostic includes the exact UTF-8 byte range; do not paste diagnostic
   fields into Phase 2M's strict evidence schema. The reviewer chooses the claim
   target and attribution and must assess semantic support. Mapping is not approval.

The pinned frontend uses JavaScript UTF-16 string positions. Phase 2M uses Python
Unicode character positions, not byte offsets. The helper converts explicit native
positions to Unicode offsets and separately reports UTF-8 byte offsets. Registered
bytes and text are never normalized, stripped or rewritten. Tests cover astral
characters, combining characters, BOM, CRLF, invalid boundaries and surrogate splits.
New content-view records use the same conversion during staging, so saved highlights
and supplemental evidence are checked in the same coordinate system. Archived Phase
2P record validation stays compatible with its original coordinate contract.

No evidence is generated for empty/pending content, absent highlights, discarded
responses or superseded revisions. Exact content hashes, provenance and current
representation membership remain mandatory. The quote is an exact selection from
registered text; it does not prove that the source is true or that the claim follows.

After completing and submitting the form, use the existing Phase 2P `stage`, inspect
the Phase 2M draft/content, then the explicit reviewer confirmation and approval
commands. Approval is separate from training-rights clearance. No labels were
approved and no training was run during this implementation.

## Validation and limits

Baseline: **400 passed, 1 skipped in 266.60 seconds**. Focused content/bridge suite:
**56 passed in 18.76 seconds**. Full post-change suite: **418 passed, 1 skipped in
249.43 seconds**, including 18 new regression cases. The skipped test is the existing
opt-in Docker smoke; live field updates, attachment and repeat import were separately
verified against the actual local server. All 118 protected legacy/source/policy/
review-packet and guard files remained byte-for-byte unchanged.

Live verification saved `data/argilla/phase2p1_live_before.json` and
`phase2p1_live_verified.json` locally. All original 24 records, including the complete
human draft, were compared against the before snapshot. Exact summary bytes matched
the displayed text; repeat import added zero records. These artifacts remain ignored.

This remains a local single-writer workflow. Prior choices are retained as context,
not silently transferred as new human responses. Historical records remain visible;
filter by content hash or use the returned current record ID after another revision.
Nested events still require the validated supplemental JSON form. The evidence helper
maps explicit highlights and does not assess entailment. No full article was retrieved.

## Repairing a submitted response with a details JSON error

The inspected submission
`submission-b4b5d4ee787f6b2e580b2773a5d1ab98e4c71b259d576538177b745f9b4aa0b8`
failed specifically while parsing **answers.details**: the saved value was a
202-character non-JSON string. It was not an empty content file, a model error or
a failed content hash. The saved domain was economics; defense event types were
the explicit `none` choice (which maps to zero categories); rationale was present.
The content/provenance binding, current representation, taxonomy/policy contract
and reviewer identity all verified. There were **zero saved native evidence spans**.
The chosen event coverage was **partial**, which requires actual event instances.
The unstructured details field supplies no validated supplemental evidence yet.
No article text, credentials or reviewer identity are reproduced in this diagnostic.

The bridge now identifies empty details, invalid JSON locations, wrong JSON root
types, missing fields, array types, absent evidence and article/event scope mistakes
with field-specific correction instructions. It never converts prose into labels,
events, evidence or approvals. Phase 2M validation itself is unchanged.

Correct the **current content-bearing record**, leaving the old metadata draft alone:

1. Open Argilla, dataset `aic-global-v2-2c8eac532566`, and the content-attached first
   SAnews record identified earlier in this guide. Inspect the registered summary.
2. Keep economics, none and rationale only if those remain your actual assessment.
   For article-level annotation with no enumerated event instances, change
   **event_coverage** to **not_enumerated** and explain that scope in the form.
   No defense event instance is required for economics. Do not choose partial and
   invent an event just to satisfy the schema.
3. Replace the **details** prose with the structured form in
   `examples/argilla_details_TEMPLATE.json`. Paste a JSON object only, without
   Markdown fences. It must have all eight fields: countries, organizations,
   event_date, event_location, evidence_status, event_coverage_note, events, evidence.
   Fill them from your actual review. Use empty arrays/null/unknown only where
   appropriate; `events: []` is valid with not_enumerated. An empty evidence array
   is deliberately invalid and must be completed.
4. Highlight the phrase supporting economics in the registered text with the
   native **support** label, then save your work. If the UI requires completing the
   supplemental form before submission, save as draft while finishing it. Save the
   current response before exporting; unsaved browser edits are not exported.

From PowerShell at the repository root:

```powershell
. ./deploy/argilla/Use-LocalArgilla.ps1
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge export
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge reconcile
```

Export retains previous immutable snapshots. Editing a response changes its exported
submission ID: use the new ID returned for the current content-bearing response,
not the old failing ID above. To map your saved first economics highlight:

```powershell
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge evidence NEW_SUBMISSION_ID --span-index 0 --target /domains/0 --attribution 'REPLACE with your actual source attribution'
```

Inspect the quote and copy only the returned inner `evidence` object into
`details.evidence`. If you assert additional entities, dates, statuses or event
claims, provide source evidence for all of them too. The helper cannot invent a
highlight and refuses absent or stale spans. Return to Argilla, finish the form
and submit it yourself. Then export again, because the details edit changed the
submission snapshot, and stage the newly returned submitted ID:

```powershell
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge export
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge stage CORRECTED_SUBMITTED_ID
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge reconcile
```

Success returns a Phase 2M **validated draft**, not an approval or rights clearance.
Inspect it using `python -m src.global_review review DRAFT_ID` before any separate
human approval decision. The existing two responses were preserved by this repair;
no actual reviewer fields, approvals, source representations or rights were changed.

Repair validation: baseline **418 passed, 1 skipped in 186.20 seconds**; focused
bridge/content/error suite **78 passed in 16.24 seconds**; final full suite
**440 passed, 1 skipped in 238.58 seconds**, including 22 new regression cases.
Live reviewer bindings matched the local server and repeated exports were identical,
without remote response changes. All 53 protected artifacts matched their pre-repair
hashes, including both exported responses, source/provenance, taxonomy/policy, legacy
records and training guards. No real annotation was fabricated, staged or approved.
