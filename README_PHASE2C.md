# AIC-1 Phase 2C: Local human annotation queue

This is an **additive patch** to Phase 1 + 2 + 2B. It does not connect to PostgreSQL, Ollama, Argus-Core, or the Internet. It makes **no automatic judgments** and does **not** create real training labels.

## Installation
Extract files into the `argus-intelligence-models` project root, preserving folders. Do not put the ZIP inside `src/`.

## Commands (PowerShell or Command Prompt; run from project root)

```bat
python -m pytest -q
python -m src.review_queue list
```

Copy `examples/intake_article_TEMPLATE.json` to `data/my_first_article.json`, replace all placeholders with a **real** article that you have the right to process, and run:

```bat
python -m src.review_queue add data/my_first_article.json --topic topics/taiwan_military_v1.json
python -m src.review_queue list
```

The `add` command prints an ID like `aic1-<32 hex characters>`. Inspect the corresponding `data/review_queue/<ID>.json` (unreviewed, not training data).

After reading the **full article** and applying `topics/taiwan_military_v1.json`, copy `examples/human_review_TEMPLATE.json` to `data/my_first_review.json` and replace **all** illustrative text and assessments with human-written judgments.

```bat
python -m src.review_queue approve YOUR_RECORD_ID data/my_first_review.json --confirm-human-review
python -m src.validate_dataset data/labeled/pilot.jsonl
```

`approve` is a manual confirmation flag; do not run it without actually reviewing the article. It validates before publishing. It requires `criteria` for Phase 2C and never accepts a machine-generated pseudo-label as human reviewed. `relevant` must satisfy all four criteria according to the Phase 2 schema.

## Important limitations
- No multi-user concurrency or file locking. **Single-user local pilot only**.
- The CLI cannot independently prove a reviewer is human. The `--confirm-human-review` flag is an explicit attestation.
- Dataset duplicate check is keyed to `source_id` + topic. It does not yet detect syndicated near-duplicates: the existing `event_group_id` remains essential for future split isolation.
- Existing Phase 1 schema permits flat records; Phase 2C's approval route requires all four structured criteria.
- Adding the placeholder templates themselves to `pilot.jsonl` would contaminate training data. Templates must remain outside the labeled dataset.
- Do not copy protected full-text articles into Git or publish private source data. Use only content you may lawfully store and train on.
