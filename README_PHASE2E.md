# AIC-1 Phase 2E — Offline candidate importer and provenance

This is an **additive patch**. Extract into your existing `argus-intelligence-models` project. It does not overwrite your earlier source files, annotations, or topic specifications.

## Verify

```bat
python -m pytest -q
python -m src.candidate_import report
```

Expected test total for the 29-test Phase 2D environment: **35 passed**. Historical approved articles may show `provenance_missing` because this patch does not retroactively invent their rights status or input type.

## Batch intake

Create `data/candidates_batch_001.jsonl` with one JSON object per line, following `examples/candidates_TEMPLATE.jsonl`. Do not submit placeholder examples as actual candidate data. Required fields are the existing five intake fields plus:

- `content_type`: `licensed_full_text`, `permitted_excerpt`, `human_summary`, `public_domain`, or `other_permitted`
- `rights_note`: nonempty description of source/permission. The tool records your statement; it does not establish licensing rights.

Run:

```bat
python -m src.candidate_import import data/candidates_batch_001.jsonl --topic topics/taiwan_military_v2.json
python -m src.review_queue list
python -m src.candidate_import report
```

**All imported articles remain pending**; no label is generated or approved. Use the existing `src.review_queue approve ... --confirm-human-review` after reviewing the article and policy.

## Safeguards and limitations

- Offline only. No scraping, Argus-Core credentials, external requests, or operational database access.
- Exact content fingerprint and normalized URL checks apply to candidates within the same topic across pending and approved records.
- Syndicated/paraphrased articles and shared events still require human grouping through `event_group_id`.
- `data/provenance/<record_id>.json` is a sidecar, not yet merged into approved JSONL. Keep it with your dataset and back it up.
- The importer is intended for single-writer development. Do not run concurrent imports/approvals.
- Batch import is not transactional. Valid lines may queue even if later lines are rejected. Re-running skips duplicate candidates.
- The data report identifies mixed policy versions and missing provenance so these can be addressed before training.
- The example template contains only placeholder data; replace it with authorized real content.
