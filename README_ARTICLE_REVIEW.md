# Article 001 final review and Article 002 intake

## Verified Article 001 state

Article 001 is staged as the immutable Phase 2M draft:

```text
draft-1f2523b43ef3bea00a722d9473302f7f9ba793a193ed73b8161610cb059e3e6c
```

Inspect the draft and the exact registered content path using:

```powershell
.\.venv-argilla\Scripts\python.exe -B -m src.global_review review draft-1f2523b43ef3bea00a722d9473302f7f9ba793a193ed73b8161610cb059e3e6c
```

Read both the displayed annotation and its source text before making any separate
approval decision. No human review-confirmation or approval command was executed
by the agent. Global approval count and eligible count remain **zero**; source
rights remain **unverified**.

The saved submission was
`submission-466b7f1b78cd012bffaebf101f2299ab616c39c0b0c28aa44bf46afca36d3db2`.
Its existing human decisions verified as economics, none for defense categories,
not_enumerated, the supplied rationale, empty country/organization/event arrays,
null date/location and unknown evidence status. The exact content hash is
`5304b76b2de6741e84f0e359c72dff7f3323e601b4cf1eaf9f63a055ef33a020`.

## Root cause and exact projection

The saved native highlights were:

| Native index | Unicode range | Supplemental mapping |
| --- | --- | --- |
| 0 | 203–331 | Existing target `/domains/0` |
| 1 | 0–202 | No target assigned |

The original supplemental quote, attribution, hash and target were correct. UTF-16
conversion produced the same coordinates here. The strict legacy bridge requires
**every** native highlight to occur in supplemental evidence, which rejected index 1.
This was a synchronization mismatch, not a verified coordinate/parser bug.

No annotation fields, labels, quotes, attribution, entities or scope were changed.
The new explicit `stage-existing` path projects only the already targeted submitted
evidence into Phase 2M, whose schema has no native-highlight field. Unassigned native
highlights remain untouched in Argilla and the immutable export. Their indexes are
recorded in a projection audit receipt for final human inspection, without inventing
targets or claiming semantic support for them. Malformed/out-of-bounds highlights
still reject the projection, including unassigned ones.

The legacy `argilla_bridge stage` check remains unchanged and will still reject
this unmodified original submission. Use the explicit evidence projection to repeat
the already completed staging operation idempotently:

```powershell
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_details stage-existing submission-466b7f1b78cd012bffaebf101f2299ab616c39c0b0c28aa44bf46afca36d3db2
```

Audit receipt:
`data/argilla/evidence-projections/projection-dfdf352b64c64541a9c0df838dbe558ab633aa9f036ca804f85e642b2bd04e21/receipt.json`.
It records `annotation_changes: []`, selected index `[0]`, unassigned index `[1]`,
and the original submission/source/contract bindings. It is a **validated draft**,
not an approval or reviewer-confirmation envelope. Existing submission history and
approval/rights safeguards are unchanged.

The local quality advisory
`data/argilla/quality-flags/quality-75b5ad146d8ddd88a9570422937b6fb3f8d8c187dda8708c9bd41a3ef09077ce/advisory.json`
flags classification-like language in the registered summary as a future **target
label leakage** risk. This advisory does not change rights or automatically decide
eligibility. A human should review a neutral, legitimately retained replacement
representation before future training use, retaining the present history. The
registered text and its hash were not edited.

## Minimal evidence-details helper

Native highlights contain ranges and a generic support label, not Phase 2M claim
paths, attribution or the nested evidence form. The former workflow therefore
required manual synchronization. `src.argilla_details` now constructs the form
from saved human highlights and explicit human-selected target paths.

- `template`: produces the safe eight-field scaffold with no entities, dates,
  organizations, events or evidence asserted. It is deliberately not staging-ready.
- `prepare`: maps saved zero-based highlight indexes to claim paths, converts
  offsets, copies exact text/hash, validates the entire annotation and writes
  `details.json` plus an audit proposal. Requires the actual reviewer's explicit
  `--confirm-evidence-mapping`; this is not human annotation approval.
- `stage-existing`: uses only valid evidence already explicitly targeted in a
  submitted supplemental form. It cannot assign new meanings or manufacture missing
  evidence. It creates a Phase 2M draft and audit, never an approval.

Neither helper edits Argilla responses. Repeating the same proposal/output is
idempotent; differing outputs require a new directory. Repeated span/target choices
are deduplicated. Stale membership, changed content/source/contract, invalid ranges,
unmatched evidence, forged quotes and incomplete claim coverage reject validation.
Prior published artifacts are never overwritten. An actor controlling the entire
local store can still forge history; existing single-writer filesystem trust applies.

## Article 002: ready for independent review, no labels assigned

- Title: **NSWC Corona hosts NATO Evolved SEASPARROW Missile Assessment**.
- Publisher: US Navy.
- Source: https://www.navy.mil/Press-Office/News-Stories/display-news/Article/4653619/nswc-corona-hosts-nato-evolved-seasparrow-missile-assessment
- Candidate: `candidate-068b7c891ed74f67f9478f9c9b28a74e75d4485ed22966360eab532401542a47`.
- Argilla record: `record-dfe42083690343c73349be87d8ab93d5318abb4fa828e1e781cc825b26fd1270`.
- State: metadata only, empty local content, **zero human responses** verified.

Open http://127.0.0.1:6900 and dataset `aic-global-v2-2c8eac532566`, then search
for the title or filter by its candidate ID. Do not infer labels from the title,
publisher, discovery score or Article 001's decisions. Read the source independently
under its access conditions. Retain only an authorized excerpt or a summary actually
written by the reviewer in:

```text
data/discovery/phase2o_001/review/002/content.txt
```

No body was retrieved or summary written for you. The packet and its original
annotation scaffold were not relabeled. A separate unfilled details scaffold and
metadata intake note are in `data/argilla/article002-preparation/`.

After supplying permitted text, run from the repository root. Replace the handling
basis and select the **actual** representation type; `human_summary` asserts actual
human authorship and is not suitable for AI prose:

```powershell
. ./deploy/argilla/Use-LocalArgilla.ps1
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge attach-sync --candidate-id candidate-068b7c891ed74f67f9478f9c9b28a74e75d4485ed22966360eab532401542a47 --text-file data/discovery/phase2o_001/review/002/content.txt --content-type human_summary --rights-note 'REPLACE with the actual handling basis; training rights unverified'
```

Open the returned content record, read its exact representation, select your own
domains/categories/scope, supply your own rationale, and highlight supporting text
using native support spans. Save as draft, then export:

```powershell
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge export
```

Only if you actually choose an article-level annotation with no individual events,
select not_enumerated and use this new-form example. `0=/domains/0` means that
**you** confirm saved highlight 0 supports the first domain you selected; change
the target/index and repeat `--span-target` for every actual claim needing support.
It does not choose a domain for you. Defense category claims, if any, also need
their own explicitly selected evidence targets. Do not use an article-only template
to discard already entered entity/date/event assertions; omit `--new-article-template`
to preserve an existing valid structured form instead.

```powershell
$prepared = .\.venv-argilla\Scripts\python.exe -B -m src.argilla_details prepare SAVED_SUBMISSION_ID --span-target '0=/domains/0' --attribution 'REPLACE with your actual source attribution' --new-article-template --scope-note 'REPLACE with your actual article/event scope explanation' --output data/argilla/article002_details_v001 --confirm-evidence-mapping | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Details preparation failed; correct the indicated field or mapping' }
./deploy/argilla/Copy-Details.ps1 -ContentPath $prepared.details_file
```

Inspect the generated proposal, then paste the clipboard into Argilla's details
question. No offset counting or copying large JSON blocks is needed. Every asserted
claim still needs valid evidence. Review all eight fields; unknown/null/empty arrays
mean no such assertion is being made, not that the source lacks those facts.
For enumerated events, use the existing complete Phase 2M event form instead of
inventing events or forcing article-only scope.

Submit the completed response yourself, export again and use the returned **new**
submission ID. If all highlights are mapped, ordinary staging works; if intentionally
retaining extra unassigned review highlights, use the explicit existing-target projection:

```powershell
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge export
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_details stage-existing NEW_SUBMITTED_ID
```

Inspect the returned Phase 2M draft and exact source before any explicit human
approval. Rights remain a separate review. None of these Article 002 annotation
commands were executed by the agent, and no Article 002 labels were assigned.

## Verification results and changed files

Baseline: **440 passed, 1 skipped in 202.21 seconds**. Focused bridge/evidence
suite with fixed hash seed: **91 passed in 20.20 seconds**. Final full suite:
**453 passed, 1 skipped in 201.28 seconds**, including 13 new evidence-helper cases.
The skipped case is the existing optional Docker smoke; live submission matching,
reviewer binding and Article 002's zero-response state were checked separately.

An initial full run exposed a pre-existing test helper that selected the last
lexicographically sorted submission hash as if it meant newest. JSON key order
could change hash order across processes. The helper now selects the exact record
and author; no production export ordering was changed or assertions weakened.

All **57 protected artifacts** matched their original hashes, including saved
responses, content revisions, source/provenance, legacy approvals, taxonomy/policy
and training safeguards. Only the intended new Phase 2M draft, projection receipt,
quality advisory and unlabeled Article 002 preparation artifacts were added locally.
The completion report is `data/argilla/article001_completion_report.json`.

This task added `src/argilla_details.py`, `tests/test_argilla_details.py` and this
guide, fixed the test-only selection helper in `tests/test_argilla_bridge.py`, and
linked the guide from README.md. Earlier uncommitted integration work was preserved.
Generated data remains ignored. Nothing was staged or committed; no approval,
rights clearance, model training or Argus repository modification was performed.

## Article 002: audited quote-encoding repair

Later verification found Article 002's human submission
`submission-531f1c8108a03867dfdd85a3e1d0ec924501fd8b6279002ee6a7770553048859`
had correct native ranges and content hash, but its first supplemental quote had
an exact reversible UTF-8-as-CP1252 transcription. U+2019 became the three code
points U+00E2, U+20AC, U+2122. This made the stored quote 177 characters instead
of the registered span's 175. The second supplemental quote was already exact.

| Evidence | Correct Unicode/UTF-16 range | Corresponding UTF-8 byte range |
| --- | --- | --- |
| `/domains/0` | 205–380 | 205–382 |
| `/defense_event_types/0` | 381–591 | 383–593 |

The offsets must **not** be changed to byte positions. The original failure was
quote mojibake, not incorrect native coordinates. The prior clipboard example used
`Get-Content -Raw` without an explicit encoding, which is unsafe in Windows
PowerShell 5.1. That documented workflow is now replaced by `Copy-Details.ps1`,
which strictly decodes UTF-8 before copying Unicode text. For a direct equivalent,
use `Get-Content -LiteralPath PATH -Raw -Encoding UTF8 | Set-Clipboard`.
Do not copy evidence JSON through an unknown console/file encoding.

The explicit opt-in repair is restricted to quotes whose original content hash
and coordinates match saved native highlights and whose stored text is **exactly**
the registered quote encoded as UTF-8 then decoded as CP1252. Both the forward and
reverse conversion must match; no replacement-character decoding, smart-quote
normalization, arbitrary transcription correction or new target choice is allowed.
The default strict validator is unchanged. The audited projection restores only
`/evidence/0/quote`; both original human highlights and submissions are preserved.

The completed operation is safe to repeat:

```powershell
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_details stage-existing submission-531f1c8108a03867dfdd85a3e1d0ec924501fd8b6279002ee6a7770553048859 --repair-quote-encoding
```

Validated Phase 2M draft:

```text
draft-ef15c772b1b55e3faefe1d731048606bb6ae715151363a379cb05399ad654662
```

Final human inspection command:

```powershell
.\.venv-argilla\Scripts\python.exe -B -m src.global_review review draft-ef15c772b1b55e3faefe1d731048606bb6ae715151363a379cb05399ad654662
```

No human approval was executed. The existing defense and military_technology
selections, not_enumerated scope, rationale and all other fields were retained.
Source SHA-256 remains
`5f66543ce4474a8f72ad51520b61ef428248e6da6646a7116198ad4a5f73f38a`.
The receipt is
`data/argilla/evidence-projections/projection-7f16f4007d70564cd52c2f825bb7b7577d474846b0e36e43839191392c8366cc/receipt.json`.
Its single change entry records the original/corrected quote hashes and unchanged
target, attribution, offsets and content identity. An original default staging
attempt still rejects the original corrupted quote; use the audited projection
rather than weakening evidence validation or rewriting history.

The current live response still matched the original export after staging. All
76 protected artifacts matched their pre-repair hashes. There is now **1 existing
global approval** (pre-existing this repair), **0 eligible global examples**, and
Article 002 rights remain **unverified**. Earlier sections retain their original
run counts. The local repair report is `data/argilla/article002_repair_report.json`.

Repair tests: **101 focused tests passed in 12.36 seconds**; full suite
**463 passed, 1 skipped in 116.07 seconds**, including 10 new regression cases.
The existing optional Docker smoke was skipped. Windows PowerShell tests mocked
the clipboard and verified exact Unicode transfer plus invalid UTF-8 rejection;
they did not change the real clipboard or persistent execution policy. Other cases
cover idempotency, preserving reviewer fields/responses, stale hashes, byte-offset
confusion, arbitrary quote mismatches and absent highlights. Four files changed:
`src/argilla_details.py`, `deploy/argilla/Copy-Details.ps1`,
`tests/test_argilla_quote_encoding.py` and this guide. No artifacts or secrets were
staged or committed.
