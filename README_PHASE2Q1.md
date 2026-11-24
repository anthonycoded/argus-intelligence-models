# Phase 2Q.1 — review persistence, transparent AI origin and compact forms

Use http://127.0.0.1:6910 and your existing Argilla account. The backend remains
the Phase 2M annotation authority; Argilla stays on port 6900. There is no new
annotation application, model call, training loop, rights-clearance endpoint or
automatic approval. Existing Phase 2R work in the working tree is preserved.

## Verified causes and repairs

The actual pre-change baseline was **513 passed, 1 skipped**, including Chromium,
rather than the older Phase 2Q count of 483. Two new disposable browser tests
failed against the old frontend before implementation:

1. **Attachment erased browser edits.** Its success handler called `load()`, which
   unconditionally replaced annotation fields, receipts, selections and work state
   with the server response. The backend also returned an empty form when the
   latest working draft belonged to the previous content revision. Attachment now
   first checkpoints the current incomplete draft, preserves field values, and
   adopts the new source binding separately. Changed source revisions invalidate
   current evidence positions, but the old source-bound draft and selections stay
   recoverable. Same-revision retries retain current mappings.
2. **Claim editing cleared all evidence.** `edit()` compared a whole-annotation
   claim signature and assigned `evidence: []` whenever any claim changed. Adding a
   fourth domain therefore removed mappings for the previous three domains and
   defense category. Validate then saved that already-cleared form. The validator
   itself was read-only. The new helper compares each exact claim path/value and
   event identity independently. Unchanged mappings survive; changed paths are
   explicitly invalidated and displayed as historical selections. No array-index
   shift silently transfers evidence to a different claim.

Validation returns actionable field paths (for example `/domains/3`) and inline
messages without replacing form state or editing saved artifacts. A failed
validation leaves the incomplete draft saved with its existing valid mappings.
Missing evidence remains mandatory: there is no schema relaxation.

Writes are single-flight in the browser, mutation controls are temporarily
disabled, and source loads/validation/selection results have generation guards.
UUID-scoped save and attachment retries are audited and idempotent. Distinct
concurrent edits still use optimistic working-version checks; an older request
cannot overwrite a newer version. Legacy callers without operation UUIDs keep
their previous stale-version rejection behavior.

The UI displays **saved**, **unsaved**, **saving**, **save failed** and **validated**.
Refreshing the queue or reselecting the current item preserves browser edits.
Leaving for another article, explicitly reloading saved state, signing out or
reloading the browser warns when unsaved changes exist. Saved drafts survive
navigation. Existing saved amendments can be explicitly resumed without changing
the original approval. Inspection revalidates the exact current staged work;
approval is disabled for dirty/unvalidated state or pending unattached content.
Backend current-head/source/inspection checks remain authoritative.

## Practical reviewer workflow

1. Select the article. You may enter labels/rationale before attachment; attaching
   will checkpoint and preserve those values.
2. Supply an authorized representation, choose its actual type and handling basis,
   then **Attach content**. For a changed revision, inspect the re-review notice
   and **Recoverable prior work**. Old offsets are historical, never current proof.
3. Select actual registered text, deliberately choose the claim targets and enter
   attribution. Click **Add supporting selection**. Each mapping displays its exact
   quote and target. You can remove it or explicitly change its target; remapping
   creates a new server-validated receipt. Mechanical text checks do not establish
   the semantic meaning or truth of evidence; that remains the reviewer's job.
4. **Save Draft**, then **Validate**. If one claim lacks evidence, existing mappings
   remain. Select the missing supporting text and target, then validate again.
5. **Submit** creates the immutable Phase 2M staged draft. **Inspect Staged Draft**
   rechecks it and shows the exact text/evidence. This phase's Article 004
   demonstration stops here. Only the actual reviewer may confirm approval.
6. Use **Reload saved article** deliberately to recover server state after a
   conflict. It warns before discarding browser edits. The history view retains
   prior working versions and source revisions.

Unattached pasted text and unmapped browser selections are not approved evidence
or durable source revisions. Attach permitted text and explicitly add its evidence
mapping before relying on Save Draft. There is no automatic keystroke storage or
crash recovery; browser unload warnings cannot protect against a process crash.

## AI-assisted representations and version compatibility

Choose **ai assisted summary** when text was generated or assisted by AI. Paste
and edit it locally; the dashboard invokes no LLM. Declare:

- generation method and human editing status;
- model/provider when known (blank stores `null`, not a guess);
- human source-review status, independently of annotation approval;
- original publisher source reference;
- whether it was based on the currently registered revision, when applicable;
- a handling basis. Source rights remain unverified without an independent decision.

New AI-assisted records use `aic-content-reference-v2` and
`aic-global-provenance-v2`, with hash-bound `aic-ai-summary-origin-v1` declarations
and the version/hash of **policies/representation_v2.json**. If an original
registered revision is claimed, it must exist with valid unchanged content and
provenance. Cyclic/excessive origin chains are rejected. Declaration of human
editing/review is not factual verification or a human annotation approval.

Legacy representations retain their v1 schemas and bytes. No stored records,
archived taxonomy or global annotation policy are migrated. The existing Argilla
contract/dataset identity and CLI interfaces stay intact. AI intake without its
origin declarations fails closed; CLI users can supply complete metadata through
the existing explicit source-registration workflow. Conflicting authorship or
handling declarations for identical existing URL/content bytes are rejected;
historical `human_summary` records are never silently reclassified.

AI assistance never grants permission to use publisher content. New text, even
if written for education or publicly accessible, does not clear training rights.
The UI and Dataset Quality inventory flag suspicious classification-like source
phrases and AI-origin quality risks. These are advisories, not automatic labels,
verified facts or rights decisions. Labels still come exclusively from independent
human review and immutable approval.

## Layout and screenshots

Desktop claims/entity controls and rationale use two columns; coverage/scope and
representation metadata use compact paired controls. Taxonomy guidance is
available in accessible disclosure controls. Retained text and evidence selection
keep their full reading width. Small viewports use one column, wrapping controls
and a consistent sticky Save/Validate/Submit action bar.

These screenshots contain only disposable fixture data and are ignored by Git:

| View | Before | After |
| --- | --- | --- |
| Desktop form | [before](data/review_dashboard/browser-evidence/phase2q1/before/attachment-desktop.png) | [after](data/review_dashboard/browser-evidence/phase2q1/after/attachment-desktop.png) |
| Narrow form | [before](data/review_dashboard/browser-evidence/phase2q1/before/attachment-narrow.png) | [after](data/review_dashboard/browser-evidence/phase2q1/after/attachment-narrow.png) |
| Missing-evidence failure | [before](data/review_dashboard/browser-evidence/phase2q1/before/missing-evidence-desktop.png) | [after](data/review_dashboard/browser-evidence/phase2q1/after/missing-evidence-desktop.png) |

Final staged fixture: [desktop](data/review_dashboard/browser-evidence/phase2q1/after/article004-staged-desktop.png),
[narrow](data/review_dashboard/browser-evidence/phase2q1/after/article004-staged-narrow.png).
The test asserts no horizontal overflow at 390 pixels wide.

## Tests and preservation

Final full run: **538 passed, 1 skipped in 279.78 seconds**, with Chromium enabled.
The new focused persistence API suite passed **18 tests**; the full run includes
all **7** new Chromium workflow tests. The TypeScript/build check passed, and
`npm test` passed **7** frontend helper tests. The separately opt-in Argilla Docker
smoke test remains skipped; one existing Starlette/httpx deprecation warning is
reported. All 242 protected preflight files retain their exact hashes. Git diff
whitespace checks pass; nothing is staged or committed (HEAD remains `63346c9`).

Changed implementation files: `dashboard/src/main.tsx`, `dashboard/src/style.css`,
`dashboard/package.json`, `src/review_dashboard.py`,
`src/review_dashboard_service.py`, `src/content_reference.py`,
`src/global_sampling.py`, `src/argilla_bridge.py` and `src/research_ledger.py`.
New helpers/policy: `dashboard/src/reviewState.ts`,
`src/representation_policy.py`, `policies/representation_v2.json`.
Tests: new `tests/test_dashboard_persistence.py`,
`tests/test_dashboard_persistence_browser.py`,
`dashboard/tests/reviewState.test.mjs`, plus the saved-amendment assertions in
`tests/test_review_dashboard.py`. Documentation: this file and the README link.
No dependency packages or archived policies changed. Pre-existing uncommitted
Phase 2R files remain in Git status and are not discarded or committed.

```powershell
$env:AIC_DASHBOARD_BROWSER='1'
$env:AIC_Q1_EVIDENCE='data/review_dashboard/browser-evidence/phase2q1/after'
.venv/Scripts/python.exe -B -m pytest tests/test_dashboard_persistence.py tests/test_dashboard_persistence_browser.py tests/test_review_dashboard.py tests/test_review_dashboard_browser.py -q -o addopts= -p no:cacheprovider
.venv/Scripts/python.exe -B -m pytest -q -o addopts= -p no:cacheprovider
Push-Location dashboard
npm.cmd run build
npm.cmd test
Pop-Location
```

The Article 004 fixture exercises attachment, four deliberately chosen domains,
one defense category, five exact evidence mappings, saved draft, a deliberate
missing-evidence failure, correction, successful validation, submission/staging
and inspection. The new workflow never approves. Existing synthetic lifecycle
tests continue to test core approval enforcement; none use production records or
actual human reviewer identities.

Other regressions cover immutable source revision recovery, field-level errors,
navigation/refresh preservation, lost-response retries, concurrent stale saves,
Unicode remapping, AI origin/policy/schema tampering and rights independence.
The frontend helper suite checks individual receipt retention and array/event
identity changes without mirroring the component implementation.

The preflight captured **242 protected existing files**, including four existing
global approvals, five legacy Taiwan annotations, provenance/rights, review
history, archived taxonomies/policies and core training guards. Current production
state is **4 approvals, 0 rights-eligible, 0 quality-accepted**, all on human
summaries. The fourth approval was already present in the preflight inventory.
The older Phase 2R three-record plan is stale and remains preserved; create a
fresh experiment configuration in Dataset Quality rather than expanding it silently.
The dataset is not ready for training/evaluation. No production article is
attached, relabeled, staged or approved by this implementation.

No commits are created. Generated sources, snapshots, screenshots, caches and
secrets remain excluded from Git. Restart only the local dashboard to load the
new Python backend; existing sessions must sign in again. Argilla itself does not
need a restart. Source rights, approval histories and Phase 2L training safeguards
remain authoritative.
