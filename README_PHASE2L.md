# Phase 2L: training safety and foundation repair

This phase retains the topic-relevance task. Global annotation integration is
Phase 2M and is not implemented here. No existing approved annotation, provenance
sidecar, policy review or rights status is migrated automatically.

## Commit boundaries

The audited baseline has 82 tests. Phase 2J/2K files existed locally but were
untracked. Recommended baseline commit, using explicit paths only:

- `README_PHASE2J.md`, `README_PHASE2K.md`
- `src/semantic_ranker.py`, `src/embedding_experiment.py`, `src/global_taxonomy.py`
- `tests/test_semantic_ranker.py`, `tests/test_global_taxonomy.py`
- `taxonomies/global_intelligence_v1.json`, `examples/global_annotation_TEMPLATE.json`

The experiment contains synthetic examples and runs only when explicitly invoked;
do not import it as a library. It is historical topic-conditioned discovery code.

Commit Phase 2L source, tests, requirements/constraints, ignore rules and this
documentation separately. Do not use `git add .`. Generated feeds, embeddings,
private datasets, model weights and credentials do not belong in either commit.
New ignore rules do not untrack previously committed files. No tracked research
artifact is removed by this phase; distribution of historical content requires a
separate review.

## Eligibility and frozen inputs

The authority is the local human-approved store and its evidence, not a
`human_verified` string or a manifest boolean alone. A Phase 2L snapshot verifies:

- structured human-approved topic annotations;
- record/source identity and normalized text fingerprint in provenance;
- exactly one explicit, cleared rights decision, attributable to a reviewer;
- exact source annotation, text and provenance hashes bound by that decision;
- matching topic and policy; an attributable, source-bound policy review when
  the approved annotation uses an older policy;
- exact approved-store, policy, snapshot and evidence hashes.

Rights attestations created from this phase onward include these identity hashes.
Older unbound rights decisions remain historical evidence but are insufficient for
a new training manifest. Additional rights decisions create a conflict, including
two identical decisions. Do not delete historical decisions or re-attest blindly
to bypass this rule. Conflict reconciliation remains a manual, separately reviewed
operation. Government origin or a human summary never automatically grants rights.

`dataset_integrity report` distinguishes nonempty snapshot eligibility from split
readiness. Snapshot creation can preserve a single eligible example; it does not
authorize training. `training_ready` stays false in that preliminary report: only
successful validation of a complete frozen split manifest permits training.

Snapshot eligibility does not require every approved record to be eligible: blocked
records are excluded and reported. Every included record must pass every check.
No current production sample is assumed eligible.

## Supported workflow

These commands require independently reviewed content, approvals and documented
rights. They are examples, not instructions to clear the existing five samples.
All commands are run from the repository root in the active virtual environment.

```powershell
python -m src.dataset_integrity report
python -m src.dataset_integrity snapshot --write --output-dir data/snapshots/pilot-2l-001
python -m src.split_dataset --input data/snapshots/pilot-2l-001/snapshot.jsonl --manifest data/snapshots/pilot-2l-001/manifest.json --out data/splits/pilot-2l-001 --seed 42
python -m src.train --data data/splits/pilot-2l-001 --manifest data/splits/pilot-2l-001/manifest.json --model C:/models/approved-local-model
```

Only the final command trains. It must not be run as part of this repair phase.
Tokenizer/model loading is local-only; weights must already be available.

Output directories must be NEW, including snapshots and split bundles. Existing
directories, even empty ones or the legacy `data/splits` with `.gitkeep`, are
refused. Complete files are staged in a sibling temporary directory and published
by directory rename. Use versioned output paths instead of overwrite/retry flags.

Legacy `freeze_snapshot(report, rows, output_dir)` is explicitly deprecated: its
caller-supplied eligibility boolean cannot establish rights. Legacy snapshots must
be regenerated from source evidence. Old raw-JSONL split/train commands are refused.
`main.py` delegates to the guarded training CLI and has no import-time training.

Before ANY ML import/model loading, the trainer validates train, validation AND
test together. It verifies exact frozen membership, all evidence, current rights
decision inventory, and deterministic allocation. Test rows participate only in
integrity checks, never training, threshold tuning or model selection. Training and
validation datasets are created from the already validated in-memory objects,
avoiding a second unchecked read of split files.

## Splitting and duplicate boundaries

Split readiness requires at least 30 eligible rows and at least three independent
leakage components containing each relevance class. Every split must contain every
class. This is only an operational sanity floor, not adequate statistical power.

Components merge transitively on event group, canonical source URL, normalized
content fingerprint, `duplicate_group_id` and `known_duplicate_group_id`. Duplicate
record IDs are rejected. Class support is reserved before allocating remaining
components by change in global allocation error toward 70/15/15. Seed and algorithm
ID (`aic1-leakage-v1`) are frozen. Sorting input records makes allocation independent
of input order. Change the algorithm ID/schema when allocation semantics change.

Ratios are approximate when groups are indivisible. Complex class/group layouts
can be conservatively refused if the greedy reservation cannot supply every class;
the diagnostic requests more independent groups. No component is split to force
ratios. Near-duplicates are only protected when identified by exact normalization
or explicit group IDs; no semantic duplicate detector or temporal holdout exists.

## XML security

Both adapters use `safe_xml.parse_xml`. The parser's `doctype` callback rejects
DTDs after decoding, including internal/external entity declarations in UTF-16.
Undefined entities fail parsing. Valid predefined XML escapes such as `&amp;`,
UTF-16 RSS and Atom remain supported. Unsupported/malformed encodings fail closed.
Byte, depth (128) and element-count (20,000) limits bound accepted trees. No external
DTD/entity resolver is installed. Keep Python/Expat security patches current.

## Windows Python 3.12 reproducibility

`requirements.txt` declares the application's dependency ranges, including
sentence-transformers. PyTorch remains an explicit CPU/CUDA installation choice.
`constraints-win-py312.txt` captures the installed dependency closure observed with
Windows x64, CPython 3.12.6. It omits unrelated optional environment packages and
contains no model weights. It was generated offline; availability of the listed
versions and a clean installation have NOT been tested in this network-restricted
session. It is a version constraint set, not a wheel-hash lock.

On a separately authorized connected machine, prepare an isolated Python 3.12
environment, install the matching CPU PyTorch wheel, then install with:

```powershell
python -m pip install -r requirements.txt -c constraints-win-py312.txt
python -m pip check
python -m pytest -q
```

For an exact offline rebuild, archive the Python installer and platform-matching
wheels for the full constraint set in an approved wheelhouse. Verify their SHA-256
inventory, install using `--no-index --find-links <wheelhouse>` and the same
requirements/constraints, then run `pip check` and the suite. Retain wheel hashes,
Python/Expat versions and `pip freeze` with the experiment environment. No network
install or external service is necessary for the local safety test suite.

## Trust and operational limits

Manifests are integrity records, not cryptographic signatures. A user able to forge
the authoritative approval store, rights evidence and all manifests can forge local
approval. Reviewer identity and rights attestations are not independently verified.
The existing local approval store remains the trust root.

Evidence paths are relative to the manifest, so preserve the source/evidence tree
when relocating a bundle. All source evidence must remain available at validation.
Appending to the approved store, editing a policy, or adding a rights decision
invalidates the old bundle; regenerate and review a new bundle. Missing files and
malformed/legacy manifests fail closed. There is no signed export, service auth,
multi-writer locking, hostile-filesystem protection, or concurrent rights-revocation
guarantee. Keep this workflow single-writer, and do not modify evidence during a run.

The test suite uses synthetic content under temporary directories and never loads
models or calls feed endpoints. Original 82 tests are retained; the grouped-split
fixture now gives each independent synthetic report distinct source/text identities
instead of incorrectly representing all reports as duplicates.
