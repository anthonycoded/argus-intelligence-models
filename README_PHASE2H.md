# Phase 2H — Automated, incremental government-feed discovery

This patch **adds** `src/feed_automation.py`, `configs/official_feeds.json`, and `tests/test_feed_automation.py` to the existing AIC-1 project. It does not alter approved labels, sources, model training, provenance, or policy reviews.

## What it does

- Fetches RSS/Atom XML over HTTPS from a **fixed allowlist** inherited from Phase 2G. Disables environment HTTP proxies and redirects; enforces a short request timeout and 2 MiB response cap. The allowlist does not establish content licensing or relevance. No arbitrary URLs or redirects are supported.
- Uses the Phase 2G XML parser and outputs discovery-only JSONL records; never fetches full articles, labels examples, auto-approves, or clears rights.
- Tracks previously discovered article IDs in a local JSON state. New discovery output is never overwritten. Raw feed XML is saved by content hash to facilitate audits.
- Ranks candidates by **title keyword matching only**. High-priority titles are selected for review; 25% of low-priority titles are deterministically selected to avoid losing every hard negative. All new discoveries are written, even the unselected ones.
- A manual run is one poll. Automatic scheduling is **not** installed by this patch; Windows Task Scheduler can invoke it periodically once local runs are validated.

## Install and test

Unzip the patch into `C:\Users\barbe\Desktop\projects\argus-intelligence-models`, merging `src/`, `configs/`, and `tests/`. Activate your existing `.venv` and run:

```bat
python -m pytest -q
python -m src.feed_automation --help
```

Expected tests: **55 passed** (48 existing + 7 new).

## First live poll

The included config has the actual US Navy feed URL you successfully tested:

```powershell
python -m src.feed_automation --config configs/official_feeds.json --output data/discovery/navy_automated_001.jsonl
```

The command returns JSON with `discovered`, `new`, `previously_seen`, `high_priority`, `low_priority_sampled`, `low_priority_skipped`, and `feed_errors`. If it fails to fetch the feed, an error is listed in `feed_errors`, not suppressed. The output is metadata-only and is not an approved dataset.

For another poll, **use a different output filename**:

```powershell
python -m src.feed_automation --config configs/official_feeds.json --output data/discovery/navy_automated_002.jsonl
```

Expect `new: 0` if the source feed has not changed. The existing `data/discovery/navy_batch_001.jsonl` from your manual Phase 2G step is **not** automatically imported into incremental state, so the first Phase 2H run may rediscover the same ten URLs. This is normal; it does not insert duplicates into approved training data.

## View selected discoveries

```powershell
@'
import json
from pathlib import Path
p = Path('data/discovery/navy_automated_001.jsonl')
for line in p.read_text(encoding='utf-8').splitlines():
    if not line.strip(): continue
    row = json.loads(line)
    if row['selected_for_review']:
        print(row['priority'], row['discovery_id'], row['article_title'])
'@ | python -
```

These discovery records remain separate from `src.government_sources prepare` and `src.candidate_import import`. Each selected candidate still needs real content, a provenance note, and independent human annotation.

## Configuration and safety

Edit `configs/official_feeds.json` to add **verified official feed URLs** under the existing government-host allowlist only. The downloader is a narrowly scoped convenience fetcher, **not** the hardened Argus-Core article-fetch transport; do not expand its hosts, enable redirects, or accept user-supplied URLs without a separate security audit. Prefer routing future network access through Argus-Core's hardened fetch service.

The `.json` state file `data/discovery/feed_seen.json` should be retained between runs and kept out of Git along with fetched XML and discovery outputs. Add the following to `.gitignore`:

```gitignore
data/discovery/
data/incoming/fetched_feeds/
```

The sampling heuristic is for **review prioritization**, not truth labeling. It is intentionally imperfect (for example, an item about unrelated 'blockade' operations may rank high). Do not use it as a relevance label or as a substitute for evaluation of recall.

## Known limitations / next steps

- Title-only matching misses military stories without recognized terms. Review a sample of unselected items; expand to search/text embeddings later.
- Feed endpoints may expire, require redirects, or throttle requests. Failures are reported, never auto-bypassed.
- The downloader has a fixed timeout per feed, not a fully hardened network-wide deadline or DNS pinning. Keep to verified government URLs; Argus-Core owns future hardened collection.
- No backfill from historical news/search archives and no automated summary creation.
- No job scheduler is installed; validate repeat polling first, then use Task Scheduler or an Argus-Core scheduled job for periodic calls.
