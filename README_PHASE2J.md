# AIC-1 Phase 2J — Local embedding ranking

This is an additive, **read-only ranking** module. It does not retrieve article bodies, change review states, classify articles, or clear usage rights. Keyword priorities are preserved for side-by-side comparison.

## Installation

Unzip into the existing `argus-intelligence-models` project root. In the activated virtual environment:

```bat
python -m pip install sentence-transformers
python -m pytest -q
```

## Rank your existing sources

From the project root, using the downloaded MiniLM model:

```bat
python -m src.semantic_ranker --inputs data/discovery/navy_automated_001.jsonl data/discovery/defensenews_001.jsonl --topic topics/taiwan_military_v2.json --output data/discovery/semantic_rank_001.jsonl
```

If the Navy automatic file only contains a selected subset, you may use `data/discovery/navy_batch_001.jsonl` instead, to compare the full ten Navy articles. Run each experiment with a new output filename; existing files are never overwritten.

The output retains each source record's original `priority`, `matched_terms`, `source_id`, etc., and adds `semantic_score`, `semantic_rank`, `ranking_basis`, and `embedding_model`. Scores are cosine similarities, **not probabilities and not relevance labels**.

## Repeat to demonstrate caching

```bat
python -m src.semantic_ranker --inputs data/discovery/navy_batch_001.jsonl data/discovery/defensenews_001.jsonl --topic topics/taiwan_military_v2.json --output data/discovery/semantic_rank_002.jsonl
```

With the same inputs and topic, most/all embeddings will be read from `data/embedding_cache`. Cache keys include model identifier and exact text; **pin an immutable Hugging Face model revision for fully reproducible research** (the default model ID may receive updates). Do not share cached embeddings publicly without checking applicable source handling requirements.

## Limitations / next checks

- **Title only**: the current source records do not include full text or feed descriptions. No attempt is made to fetch copyrighted text. Evaluate recall against human-reviewed articles before automation.
- Missing titles are skipped and counted. Duplicate `source_id` values across files are ranked once.
- Model inference runs on CPU; on first run, the public model is downloaded from Hugging Face.
- The cache is local and not intended for concurrent writer processes.
- Ranking reads discovery files only and does not change `pilot.jsonl` or any review queue.
- Keep low-scoring candidates available for human review; rank alone does not justify dropping articles.
