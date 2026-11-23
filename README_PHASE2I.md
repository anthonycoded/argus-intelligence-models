# AIC-1 Phase 2I — Defense News Asia-Pacific feed

This is an **additive** patch: it introduces `src/news_feeds.py` and `tests/test_news_feeds.py`. It does not modify the 55 existing tests, official feed collector, policies, training labels, or database.

Defense News is a **commercial publisher**, not a government source. Keep its separate downloader and seen-state file isolated from the government collector. This adapter only retrieves RSS metadata: article URLs, headlines, publication dates, and discovery IDs. It does not fetch full article pages, clear rights, or approve labels.

## Install

Extract the patch into `C:\Users\barbe\Desktop\projects\argus-intelligence-models` and merge the `src` and `tests` folders.

```bat
python -m pytest -q
python -m src.news_feeds --output data/discovery/defensenews_001.jsonl
```

Run again with a **different output file** to test state deduplication:

```bat
python -m src.news_feeds --output data/discovery/defensenews_002.jsonl
```

Use the default URL `https://www.defensenews.com/global/asia-pacific/feed/`. If the publisher blocks automated download or redirects, the command reports a failure: don't bypass access controls. The site currently serves XML, but a successful live download is not guaranteed on every network.

## Show new candidates

In PowerShell:

```powershell
@'
import json
from pathlib import Path
p=Path('data/discovery/defensenews_001.jsonl')
for line in p.read_text(encoding='utf-8').splitlines():
    if line.strip():
        row=json.loads(line)
        print(row['priority'], row['discovery_id'], row['article_title'], row['source_id'])
'@ | python -
```

`high` means the title matched a keyword heuristic, not that the article is relevant. The next step is to select suitable articles and supply an authorized excerpt or original summary to the existing human-annotation queue. Do not copy the commercial RSS feed's full text into a training corpus by default.

The state is `data/discovery/defensenews_seen.json`, separate from `data/discovery/feed_seen.json` used for government feeds. The new discovery JSONL and raw XML are saved under `data/discovery/` and should remain out of Git.

## Caveats

- Historical searching and content-aware ranking are not implemented here.
- HTTP requests use HTTPS, an exact host allowlist, no redirects/proxies, a 12-second timeout, and a 2 MiB response cap. This is still not Argus-Core's DNS-pinned SSRF-hardened fetcher; keep it limited to this fixed feed endpoint.
- The importer in Phase 2E can accept prepared article candidates later. This module deliberately does not import discovered metadata as labeled records.
