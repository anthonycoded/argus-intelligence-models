# Phase 2R — research dataset preparation

Phase 2R adds a local Dataset Quality view, an auditable research ledger and
deterministic metadata-only split plans. It does not train, load weights, download
a model, approve annotations or change rights. There are no new dependencies.
Use the existing dashboard environments and dependency constraints documented in
README_PHASE2Q.md.

## GUI-first process

1. Start the existing local service with `powershell -File deploy/Start-Review.ps1`,
   open http://127.0.0.1:6910 and sign in with your Argilla reviewer account.
2. Click **Dataset Quality**. Review counts, labels, evidence coverage, publisher
   diversity, representation types, advisory flags and readiness blockers.
   Publisher origin is displayed separately from approved country/role assertions
   and human-reviewed event regions. Missing geography remains unknown.
3. Click **Capture inventory** to retain a technical snapshot. This action has
   no human annotation, quality acceptance or rights-clearance effect.
4. For each record, choose **Review quality and grouping**. Inspect its source in
   **Article review** first. Record your observations and deliberately choose
   `accepted`, `needs_review` or `excluded`. Enter event groups shared by articles
   covering the same event; add known duplicate groups when appropriate. Enter
   regions and language only when supported. Confirm that you personally reviewed
   these observations, then **Record quality version**. Empty/unknown grouping,
   language or regions blocks real export. Existing decisions remain in history.
5. Select records, give the experiment a name and an inclusion/exclusion rationale,
   and choose an explicit integer seed. **Save experiment configuration**, then
   **Create frozen split preview**. The rationale is recorded for included and
   excluded records. Saved configurations and plans can be reopened after reload;
   stale configurations must be recreated against the current inventory.
6. Inspect the train/validation/test assignments and **Validate saved plan**.
   These are identifiers and label metadata, not article text or a training
   manifest. A small or highly connected set can leave partitions empty.
7. **Export rights-checked dataset** remains disabled until selected records meet
   all gates and you confirm grouping review. The server independently rechecks
   everything and delegates to the unchanged Phase 2N frozen dataset exporter.
   The GUI has no rights-clearance control. `research_only` never grants rights.
8. Optionally record an external result with a numeric metric and run notes.
   Results are expressly user-supplied and unverified; the dashboard computes no
   model metrics and executes no model. Record exact environment/configuration
   and run identity in the notes.

Selecting a different cohort clears the active experiment to prevent exporting
an older selection accidentally. Changing quality, approvals, source bindings or
rights invalidates previous inventories/plans; their historical files remain.

## Storage and guarantees

`data/review_dashboard/research/` is ignored by Git. It contains content-addressed,
versioned `events/`, `experiments/`, `plans/`, `cohorts/` and real `exports/`.
Events bind the previous event, sequential index, authenticated actor, UTC time,
operation UUID and payload. Operation retries are idempotent; reused UUIDs with
different payloads and stale ledger heads are rejected. Publication uses an OS
writer lock. Existing files are never overwritten. Hash chains detect internal
edits, missing ancestors and forks; this is an auditable local store, not a signed
external transparency log. A filesystem administrator can roll back the entire
store, including the last events; back it up separately for stronger retention.

Inventory rows reference source binding/provenance hashes, representation record
IDs, exact content hash, approval ID/hash, taxonomy/policy hashes, immutable human
labels, rights decision hashes, quality review version, observations and blockers.
Only current, core-validated human approvals are included. Drafts, model scores and
legacy Taiwan relevance annotations do not become global targets.

Planning preserves transitive components across source/approval identity, canonical
URL, exact/normalized content, manually reviewed event/duplicate groups, and
conservative related-content hints. Near-duplicate hints use normalized five-token
Jaccard similarity ≥ 0.8 over at most 5,000 tokens per record; they are advisory,
not semantic judgments. The pairwise scan is quadratic and intended for this
small research pilot. Unrecognized paraphrases/events still require human grouping.
Seeded group allocation balances defense/nondefense targets approximately; exact
ratios are impossible for some connected groups. The algorithm is versioned in
each manifest. API callers may use other positive ratios summing to one for
previews, but the protected exporter supports only its existing 70/15/15 policy.

Snapshot eligibility, quality acceptance, rights eligibility, split readiness and
training support are different states. A cleared, accepted snapshot can be frozen
before it meets the existing minimum of 30 rows and three independent components
per defense/nondefense class. Real exports revalidate immutable approval/content/
provenance identity and rights through `src.global_dataset`; they remain unsuitable
for the legacy topic-specific `src.train` interface. No global training entry
point is introduced. Dataset-quality readiness does not mean a model was trained.

Leakage flags are heuristic, not automatic relabeling/exclusion. In particular,
Article 001's human summary contains classification-like phrasing. Review its
quality independently before future use as model input; do not silently rewrite
its approved representation. Accepted quality does not clear rights.

## Offline educational dry run

From the repository root, using the existing Windows Python environment:

```powershell
.venv/Scripts/python.exe -B -m src.research_ledger fixture --output data/educational_runs/phase2r-v1 --seed 42
.venv/Scripts/python.exe -B -m src.research_ledger validate-fixture data/educational_runs/phase2r-v1
.venv/Scripts/python.exe -B -m src.research_ledger summary
# Substitute the plan identifier displayed by the GUI:
.venv/Scripts/python.exe -B -m src.research_ledger validate-plan plan-<64-hex-hash>
```

The fixture generator creates 60 explicitly synthetic, authored-target examples
in 30 indivisible groups: 42 train, 10 validation and 8 test records. Equal seeds
produce byte-identical files. Existing destinations are refused. The independent
fixture schema has `synthetic_only: true`, `human_approved: false` and
`production_export_compatible: false`; the production dataset validator rejects it.
It has no source approvals or rights decisions, and never mixes with the review
store. Do not import it as human-reviewed global intelligence data.

`config/education_phase2r_v1.json` is a versioned starter configuration for your
future user-written PyTorch/Hugging Face experiment. In a later, user-operated
exercise, validate this synthetic fixture first, seed Python/NumPy/PyTorch, build
datasets from exactly its saved partitions, load only explicitly chosen local
weights, and implement your own tokenizer/DataLoader/training loop. Keep the
test split untouched until final evaluation; report precision/recall/F1 and the
confusion matrix, exact split hash, configuration, environment and run seed.
Its easy authored targets cannot estimate real-world performance. Phase 2R
provides validation/configuration only and runs none of these training steps.

For future real-data work, implement a separately reviewed global training
contract that calls `global_dataset.validate_dataset` and checks current quality,
rights and supervised split readiness before importing model libraries. A metadata
research plan or synthetic fixture must never satisfy that contract. Existing
Phase 2L legacy training guards are unchanged.

## Verified pilot readiness

At implementation time: **3 human-approved global annotations; 0 rights-eligible;
0 quality-accepted; 0 fully eligible**. Approved domains: economics 2, geopolitics
1, defense 1 (multi-label counts overlap). The sole defense category is
`military_technology`. Publishers: SAnews, UK Government, US Navy. All three are
human summaries. Publisher-origin coverage is Africa/Europe/North America; no
approved country/role assertions or reviewed event-region metadata establish
event-geographical diversity. The broader queue remains 24 candidates.

A technical inventory and research-only configuration were captured without
human quality decisions. The saved metadata preview is
`plan-850da8797a52ec54d36ff130c0ba70c66203dbc9028b5825ffa67855e66f9153`.
For this three-record cohort and seed, all records fall in train; validation/test
are empty. This is an explicitly insufficient pilot preview, not an evaluation
dataset. Reopen it under **Saved configurations and plans** in the GUI. The
isolated 60-record synthetic fixture is already present at
`data/educational_runs/phase2r-v1`; validate it with the command above rather than
regenerating over its immutable destination.

The pilot is **not ready for supervised training or evaluation**. Next: review
summary leakage/quality and shared-event grouping, document legitimate rights
decisions independently, collect more independently reviewed defense and
nondefense examples, and meet class/group support requirements. No existing
rights assessment or annotation is changed by this phase.

## Validation

Final verified run: **513 passed, 1 skipped** with Chromium enabled; all **30**
Phase 2R focused tests passed. The skipped test is the separately opt-in local
Argilla Docker smoke test. The suite reports one existing Starlette/httpx
deprecation warning. `npm run build` (TypeScript validation and bundling) passed.
All 213 preflight-protected files, including legacy approvals, global history,
provenance and core training guards, retained their exact hashes. No commit was
created; generated ledger, fixture and frontend build artifacts remain ignored.

The regression tests use disposable sources and approvals only. They cover
versioned/idempotent ledger writes, stale content/provenance, tampering, rights
restrictions/conflicts, deterministic grouped plans, segregated fixtures and
authenticated/CSRF-protected dashboard access. The opt-in Chromium test also
checks Dataset Quality navigation and technical inventory capture after the
existing disposable annotation workflow.

```powershell
$env:AIC_DASHBOARD_BROWSER='1'
.venv/Scripts/python.exe -B -m pytest -q -o addopts= -p no:cacheprovider
cd dashboard
npm.cmd run build
```

CLI store access needs the same filesystem permissions as the local service.
Never relax permissions on protected provenance/history to work around an error.
