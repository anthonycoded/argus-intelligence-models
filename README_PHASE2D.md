# AIC-1 Phase 2D: versioned Taiwan v2 policy

This additive patch **does not overwrite** `topics/taiwan_military_v1.json`, previously approved JSONL records, or existing tests.

## Install
Extract this archive into the `argus-intelligence-models` project directory, merging `src/`, `topics/`, `tests/`, and `examples/`.

## Verify
```bat
python -m src.topic_spec topics/taiwan_military_v2.json
python -m pytest -q
python -m src.validate_dataset data/labeled/pilot.jsonl
```
The additive patch has six tests, so with the previously verified 23 tests, expect **29 passed** if the environment matches.

## Why v2?
- Detailed current Chinese operations may qualify even if the headline is diplomatic.
- Historical Chinese operations substantially analyzed can qualify as relevant.
- Historical Chinese operations given as supporting context for another country's current operations are a *provisional* partial-relevance candidate, not automatically relevant.
- General, passing military mentions are unrelated unless there is a substantive connection.
- Distinguish Chinese Coast Guard activity from PLA activity; record the actual operational evidence rather than assuming identical roles.

`examples/taiwan_policy_v2_regression_cases.json` lists **proposed expected labels**, not human-ground-truth labels. Its tests validate fixture structure and the intent of policy examples; they do **not** establish factual correctness or automatically classify real articles.

## Optional: explicitly re-pin Article 004 (pending only)
If you personally accept the v2 policy, update the policy pinned to Article 004, without changing its identity or article text:

```bat
python -m src.retarget_pending aic1-9933f3f2046747048876b7cef00b17f7 --topic topics/taiwan_military_v2.json --confirm-policy-change
```

This command only modifies the **pending** record; it will **not** approve an annotation. The record will retain its original ID and gain `policy_change_history`. Existing approved Articles 001–003 continue to use v1.

Before approving Article 004, review the full source, the previously entered summary, and each criterion. The candidate `partially_relevant` label under v2 is **not automatically correct**. If the source in fact substantively analyzes Chinese operations, `relevant` may still be defensible. Do not mark any review as human-verified without checking it yourself.

## Future work
Store an explicit `text_provenance` for every record (full article / authorized excerpt / human-authored summary), because summaries can shift the apparent relevance class. Add a dedicated review migration with an audit trail if you later choose to re-annotate approved data under v2.
