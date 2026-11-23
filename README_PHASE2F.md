# Phase 2F: dataset integrity

Offline, additive. Does **not** edit `data/labeled/pilot.jsonl`, connect to Argus-Core, automatically relabel, or license any source.

## Install

Extract patch in the AIC-1 project root, preserving `src/`, `tests/`, and this README.

```bat
python -m pytest -q
python -m src.dataset_integrity backfill
python -m src.candidate_import report
python -m src.dataset_integrity report
```

The backfill creates **missing** `data/provenance/aic1-*.json` sidecars; it never overwrites existing provenance. Historical article types are identified from the four known pilot record IDs; all rights start `unverified`. Existing records remain byte-for-byte unchanged.

## Review previous v1 records against v2

For each v1 record, copy and edit a review file with **exactly** `label`, `rationale`, and `criteria` (same structure as `examples/human_review_TEMPLATE.json`). Evaluate against `topics/taiwan_military_v2.json`; do not blindly reuse the old assessment.

```bat
python -m src.dataset_integrity review RECORD_ID data\v2_review_001.json --reviewer YOUR_REVIEWER_ID --confirm-human-review
```

This creates an append-only file `data/policy_reviews/RECORD_ID__aic1-taiwan-v2.json`. The approved JSONL remains unchanged. You can review the original three records; the already-v2 Article 004 requires no v2 re-review.

## Rights status

The backfill does **not** confer training permission. To document a decision after checking the rights applicable to your planned use:

```bat
python -m src.dataset_integrity rights RECORD_ID --status restricted --content-type reported_full_text --evidence "Rights not established for model training" --reviewer YOUR_REVIEWER_ID
```

Use `--status cleared` **only when there is a genuine documented basis** for the intended training use. The text in `--evidence` is an attestation, **not an independent legal evaluation**. For the four current records, leave status unverified until evaluated.

Only one rights decision per record is accepted as effective; any additional decision creates an explicit conflict that blocks training until manually reconciled. Never delete decisions merely to get around a restriction.

## Inspect eligibility / freeze

```bat
python -m src.dataset_integrity report
python -m src.dataset_integrity snapshot
```

These are read-only. They explain why each record is excluded. `snapshot --write` creates a snapshot *only* if there are at least 20 eligible examples, 3 examples per class, and 10 event groups. No train/validation/test splits are generated here; grouping and time leakage rules are a subsequent milestone.

## Important current limitations

- Rights checks are human-supplied attestations, not legal verification.
- Source text may be a summary or copyrighted original; metadata must reflect that distinction.
- The code is designed for a single-writer local CLI workflow, not concurrent multi-user access.
- Prior v1 labels stay as originally recorded; v2 reviews create independent, attributable revisions.
- The existing Phase 2E quality report recognizes the newly created provenance sidecars but does not infer usage permissions.
