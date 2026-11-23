"""Allowlisted feed download + incremental, review-only prioritization.

No full-text downloading, training-rights changes, approvals, or model inference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import ssl
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .government_sources import MAX_FEED_BYTES, allowed_url, parse_feed_file

MAX_CONFIG_BYTES = 64 * 1024
MAX_STATE_BYTES = 8 * 1024 * 1024
MAX_SOURCES = 20
MAX_SEEN = 100000
MAX_FEED_ITEMS = 500
TOPIC_TERMS = (
    "taiwan", "taiwan strait", "pla", "people's liberation army",
    "chinese military", "chinese navy", "chinese naval", "china coast guard",
    "eastern theater command", "eastern theatre command", "blockade",
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_feed_url(url: str) -> None:
    # Fixed domain allowlist; never permit user-supplied custom hosts.
    if not allowed_url(url):
        raise ValueError("Feed URL must be HTTPS on an approved government hostname")
    p = urlsplit(url)
    if p.fragment or '\\' in url or any(ord(c) < 32 for c in url):
        raise ValueError("Feed URL contains forbidden characters")


def load_config(path: Path) -> list[dict]:
    if path.stat().st_size > MAX_CONFIG_BYTES:
        raise ValueError("Configuration too large")
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    feeds = obj.get("feeds") if isinstance(obj, dict) else None
    if not isinstance(feeds, list) or not (1 <= len(feeds) <= MAX_SOURCES):
        raise ValueError("Configuration needs 1-20 feeds")
    ids, result = set(), []
    for feed in feeds:
        if not isinstance(feed, dict) or set(feed) != {"id", "url"}:
            raise ValueError("Each feed must contain only id and url")
        name, url = feed["id"], feed["url"]
        if not isinstance(name, str) or not (1 <= len(name) <= 50) or not all(c.isalnum() or c in "-_" for c in name):
            raise ValueError("Invalid feed ID")
        if name in ids:
            raise ValueError("Duplicate feed ID")
        if not isinstance(url, str):
            raise ValueError("Invalid URL")
        validate_feed_url(url)
        ids.add(name)
        result.append({"id": name, "url": url})
    return result


def fetch_feed(url: str, *, timeout: float = 12.0) -> bytes:
    """Fetch only a known HTTPS government feed; no redirects/proxies; 2 MiB cap.

    This is NOT a general-purpose SSRF-safe internet fetcher. No untrusted URLs,
    DNS override, extra host roots, or redirects should be added without review.
    """
    validate_feed_url(url)
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    req = Request(url, headers={"User-Agent": "AIC1FeedCollector/0.1", "Accept": "application/rss+xml, application/atom+xml, text/xml, application/xml"})
    try:
        with opener.open(req, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError(f"Unexpected HTTP status: {response.status}")
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > MAX_FEED_BYTES:
                raise ValueError("Feed exceeds 2 MiB")
            raw = response.read(MAX_FEED_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, socket.timeout) as exc:
        raise ValueError(f"Feed fetch failed: {type(exc).__name__}") from exc
    if len(raw) > MAX_FEED_BYTES:
        raise ValueError("Feed exceeds 2 MiB")
    return raw


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".aic1-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_state(path: Path) -> set[str]:
    if not path.exists():
        return set()
    if path.stat().st_size > MAX_STATE_BYTES:
        raise ValueError("State too large")
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("schema_version") != 1 or not isinstance(state.get("seen"), list):
        raise ValueError("Invalid state format")
    seen = state["seen"]
    if len(seen) > MAX_SEEN or any(not isinstance(x, str) or len(x) != 20 for x in seen):
        raise ValueError("Invalid state contents")
    return set(seen)


def priority(title: str) -> tuple[str, list[str]]:
    lower = title.casefold()
    matched = sorted(term for term in TOPIC_TERMS if term in lower)
    return ("high" if matched else "low"), matched


def collect(feeds: list[dict], *, output: Path, state: Path, feed_dir: Path,
            low_sample_pct: int = 25, fetcher=fetch_feed, now: str | None = None) -> dict:
    if not (0 <= low_sample_pct <= 100):
        raise ValueError("Low sample percent must be 0-100")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite output: {output}")
    seen = read_state(state)
    timestamp = now or datetime.now(timezone.utc).isoformat()
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Collected timestamp needs timezone")
    rows, within_run, stats = [], set(), {"feeds": len(feeds), "discovered": 0, "new": 0, "previously_seen": 0, "duplicate_in_batch": 0, "high_priority": 0, "low_priority_sampled": 0, "low_priority_skipped": 0, "feed_errors": {}}
    # Fail on an individual invalid/failed feed without poisoning state; other feeds proceed.
    for feed in feeds:
        name, url = feed["id"], feed["url"]
        try:
            raw = fetcher(url)
            # Parse the downloaded bytes via the existing hardened-offline parser.
            digest = hashlib.sha256(raw).hexdigest()[:16]
            path = feed_dir / f"{name}-{digest}.xml"
            if not path.exists():
                atomic_write(path, raw)
            parsed, counts = parse_feed_file(path, collected_at=timestamp)
            if counts["total"] > MAX_FEED_ITEMS:
                raise ValueError("Too many entries in feed")
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            stats["feed_errors"][name] = str(exc)[:180]
            continue
        stats["discovered"] += len(parsed)
        for article in parsed:
            aid = article["discovery_id"]
            if aid in seen:
                stats["previously_seen"] += 1
                continue
            if aid in within_run:
                stats["duplicate_in_batch"] += 1
                continue
            within_run.add(aid)
            rank, terms = priority(article["article_title"])
            if rank == "high":
                stats["high_priority"] += 1
            else:
                # Deterministic sampling, same URL always receives same treatment.
                sample = int(hashlib.sha256(aid.encode()).hexdigest()[:8], 16) % 100 < low_sample_pct
                if sample:
                    stats["low_priority_sampled"] += 1
                else:
                    stats["low_priority_skipped"] += 1
            article.update({"feed_id": name, "priority": rank, "matched_terms": terms,
                            "selected_for_review": (rank == "high" or sample) if rank == "low" else True})
            rows.append(article)
    # Emit all new discoveries, including low-priority ones, so nothing is silently discarded.
    if len(seen | within_run) > MAX_SEEN:
        raise ValueError("State capacity reached; archive/rotate state before proceeding")
    content = ''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in rows).encode("utf-8")
    atomic_write(output, content)
    # Only after output commits: mark all discovered new IDs as processed.
    atomic_write(state, json.dumps({"schema_version": 1, "seen": sorted(seen | within_run)}, indent=2).encode())
    stats["new"] = len(rows)
    stats.update({"output": str(output), "state": str(state)})
    return stats


def main() -> None:
    # Historical collect()/priority() APIs remain available for explicit topic
    # experiments. Default collection has no topic heuristic or regional filter.
    from .global_feeds import main as global_main
    global_main()


if __name__ == "__main__":
    main()
