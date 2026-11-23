"""Offline, allowlisted RSS/Atom discovery for AIC-1.

Discover metadata first; a human must supply rights-reviewed text before candidate import.
No network calls, auto-labels, rights approvals, or operational database access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .candidate_import import ALLOWED_TYPES, canonical_source
from .safe_xml import parse_xml

MAX_FEED_BYTES = 2 * 1024 * 1024
ALLOWED_HOST_ROOTS = (
    "defense.gov", "state.gov", "gao.gov", "congress.gov", "dni.gov", "navy.mil",
)


def allowed_url(url: str, roots: tuple[str, ...] = ALLOWED_HOST_ROOTS) -> bool:
    if not isinstance(url, str) or any(c.isspace() for c in url):
        return False
    try:
        p = urlsplit(url)
        if p.scheme.lower() != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
            return False
        hostname = p.hostname.lower().rstrip(".")
        return any(hostname == root or hostname.endswith("." + root) for root in roots)
    except ValueError:
        return False


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def child_text(el: ET.Element, name: str) -> str:
    for ch in el:
        if local_name(ch.tag) == name:
            return " ".join("".join(ch.itertext()).split())
    return ""


def entry_link(el: ET.Element) -> str:
    # RSS <link>url</link>; Atom <link href="..." rel="alternate" />
    for ch in el:
        if local_name(ch.tag) != "link":
            continue
        if ch.attrib.get("href"):
            if ch.attrib.get("rel", "alternate") == "alternate":
                return ch.attrib["href"].strip()
        elif (ch.text or "").strip():
            return ch.text.strip()
    return ""


def parse_feed_file(path: Path, collected_at: str | None = None) -> tuple[list[dict], dict]:
    if path.stat().st_size > MAX_FEED_BYTES:
        raise ValueError("Feed exceeds 2 MiB safety limit")
    raw = path.read_bytes()
    root = parse_xml(raw, MAX_FEED_BYTES)
    top = local_name(root.tag)
    if top == "rss":
        channel = next((x for x in root if local_name(x.tag) == "channel"), None)
        if channel is None:
            raise ValueError("RSS missing channel")
        entries = [x for x in channel if local_name(x.tag) == "item"]
    elif top == "feed":
        entries = [x for x in root if local_name(x.tag) == "entry"]
    else:
        raise ValueError("Only RSS 2.x and Atom feeds supported")
    timestamp = collected_at or datetime.now(timezone.utc).isoformat()
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timestamp must have timezone")
    found, seen = [], set()
    counts = {"total": len(entries), "accepted": 0, "unsupported_host": 0, "invalid": 0, "duplicate": 0}
    for entry in entries:
        title, link = child_text(entry, "title"), entry_link(entry)
        if not title or not link:
            counts["invalid"] += 1
            continue
        if not allowed_url(link):
            counts["unsupported_host"] += 1
            continue
        source = canonical_source(link)
        if source in seen:
            counts["duplicate"] += 1
            continue
        seen.add(source)
        source_id = hashlib.sha256(source.encode()).hexdigest()[:20]
        found.append({
            "discovery_id": source_id,
            "source_id": source,
            "article_title": title,
            "published_at_raw": child_text(entry, "pubdate") or child_text(entry, "updated") or child_text(entry, "published") or None,
            "collected_at": timestamp,
            "discovered_from_file": path.name,
            "review_status": "discovered_unreviewed",
        })
        counts["accepted"] += 1
    return found, counts


def write_discovery(records: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    with output.open("x", encoding="utf-8") as f:
        for row in records:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def prepare_candidate(discovery_file: Path, discovery_id: str, text_path: Path,
                      content_type: str, rights_note: str, event_group_id: str,
                      batch_output: Path) -> dict:
    if content_type not in ALLOWED_TYPES:
        raise ValueError("Invalid content type")
    if not rights_note.strip() or not event_group_id.strip():
        raise ValueError("Nonempty rights note and event group required")
    if text_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Text too large")
    text = text_path.read_text(encoding="utf-8-sig").strip()
    if len(text) < 100:
        raise ValueError("Need at least 100 characters of independently reviewed source text")
    items = [json.loads(line) for line in discovery_file.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    matches = [r for r in items if r.get("discovery_id") == discovery_id]
    if len(matches) != 1:
        raise ValueError("Discovery ID must match exactly one record")
    item = matches[0]
    if not allowed_url(item["source_id"]) or item.get("review_status") != "discovered_unreviewed":
        raise ValueError("Unsupported or modified discovery")
    candidate = {
        "event_group_id": event_group_id,
        "source_id": item["source_id"],
        "collected_at": item["collected_at"],
        "article_title": item["article_title"],
        "article_text": text,
        "content_type": content_type,
        "rights_note": rights_note.strip() + " [Human-supplied assertion; training rights remain unverified until separate attestation.]",
    }
    batch_output.parent.mkdir(parents=True, exist_ok=True)
    # Append only to candidate batch, never to approved or provenance records.
    with batch_output.open("a", encoding="utf-8") as f:
        f.write(json.dumps(candidate, ensure_ascii=False) + "\n")
    return {"prepared": 1, "batch_file": str(batch_output), "source_id": item["source_id"]}


def main() -> None:
    p = argparse.ArgumentParser(description="Offline allowlisted government RSS/Atom discovery. No rights or labels auto-approved.")
    cmds = p.add_subparsers(dest="command", required=True)
    d = cmds.add_parser("discover")
    d.add_argument("feed_xml", type=Path)
    d.add_argument("--output", type=Path, required=True)
    d.add_argument("--collected-at")
    c = cmds.add_parser("prepare")
    c.add_argument("discovery_jsonl", type=Path)
    c.add_argument("discovery_id")
    c.add_argument("--text-file", type=Path, required=True)
    c.add_argument("--content-type", choices=sorted(ALLOWED_TYPES), required=True)
    c.add_argument("--rights-note", required=True)
    c.add_argument("--event-group-id", required=True)
    c.add_argument("--batch-output", type=Path, required=True)
    args = p.parse_args()
    if args.command == "discover":
        rows, counts = parse_feed_file(args.feed_xml, args.collected_at)
        write_discovery(rows, args.output)
        print(json.dumps({**counts, "output": str(args.output)}, indent=2))
    else:
        print(json.dumps(prepare_candidate(args.discovery_jsonl, args.discovery_id,
              args.text_file, args.content_type, args.rights_note,
              args.event_group_id, args.batch_output), indent=2))


if __name__ == "__main__":
    main()
