"""Import user-supplied, permitted candidate records into the existing human review queue.

No network access, no automatic labels, and no writes to approved data.
Provenance is stored in a separate sidecar keyed by the generated record ID.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .review_queue import INPUT_FIELDS, add_article
from .schema import read_records

ALLOWED_TYPES = {"licensed_full_text", "permitted_excerpt", "human_summary", "public_domain", "other_permitted"}
TRACKING = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def canonical_source(value: str) -> str:
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return value
    host = parts.hostname.lower()
    if parts.port and parts.port not in (80, 443):
        host += f":{parts.port}"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                             if not k.lower().startswith("utm_") and k.lower() not in TRACKING))
    return urlunsplit((parts.scheme.lower(), host, parts.path.rstrip("/") or "/", query, ""))


def fingerprint(text: str) -> str:
    return hashlib.sha256(" ".join(text.casefold().split()).encode("utf-8")).hexdigest()


def _read_rows(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows = []
    for line, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Candidate line {line}: invalid JSON: {exc}") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"Candidate line {line}: expected JSON object")
        rows.append(obj)
    return rows


def _existing(queue_dir: Path, approved_path: Path):
    rows = []
    for path in sorted(queue_dir.glob('*.json')) if queue_dir.exists() else []:
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    if approved_path.is_file():
        rows.extend(read_records(approved_path))
    return rows


def import_batch(batch: Path, topic: Path, queue_dir: Path, approved: Path, provenance_dir: Path) -> dict:
    rows = _read_rows(batch)
    existing = _existing(queue_dir, approved)
    known_urls = {(r.get("topic_id") or r.get("topic"), canonical_source(r["source_id"])) for r in existing}
    known_fingerprints = {(r.get("topic_id") or r.get("topic"), fingerprint(r["article_text"])) for r in existing}
    # Topic identity is consistent across v1/v2 and subsequent versions.
    from .topic_spec import read_topic_spec
    spec = read_topic_spec(topic)
    key = spec["topic_id"]
    known_urls = {(key if k in (key, spec['title']) else k, url) for k, url in known_urls}
    known_fingerprints = {(key if k in (key, spec['title']) else k, fp) for k, fp in known_fingerprints}
    counts = Counter()
    ids = []
    for lineno, row in enumerate(rows, 1):
        try:
            if set(row) != set(INPUT_FIELDS) | {"content_type", "rights_note"}:
                raise ValueError("expected five intake fields plus content_type and rights_note")
            if row["content_type"] not in ALLOWED_TYPES:
                raise ValueError(f"invalid content_type: {row['content_type']!r}")
            if not isinstance(row["rights_note"], str) or not row["rights_note"].strip():
                raise ValueError("rights_note must be a nonempty string")
            url = canonical_source(row["source_id"])
            fp = fingerprint(row["article_text"])
            if (key, url) in known_urls or (key, fp) in known_fingerprints:
                counts["duplicate"] += 1
                continue
            intake = {field: row[field] for field in INPUT_FIELDS}
            # Existing queue validates the exact intake structure and timestamp.
            temp = provenance_dir / f".intake_{lineno}.json"
            provenance_dir.mkdir(parents=True, exist_ok=True)
            try:
                temp.write_text(json.dumps(intake, ensure_ascii=False), encoding="utf-8")
                record_id = add_article(temp, topic, queue_dir, approved)
            finally:
                temp.unlink(missing_ok=True)
            sidecar = {
                "record_id": record_id,
                "content_type": row["content_type"],
                "rights_note": row["rights_note"],
                "canonical_source_id": url,
                "text_sha256": fp,
                "import_batch": batch.name,
                "import_line": lineno,
            }
            (provenance_dir / f"{record_id}.json").write_text(json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            known_urls.add((key, url))
            known_fingerprints.add((key, fp))
            counts["queued"] += 1
            ids.append(record_id)
        except (TypeError, KeyError, ValueError) as exc:
            counts["invalid"] += 1
            print(f"Line {lineno}: rejected ({exc})")
    return {"queued": counts["queued"], "duplicate": counts["duplicate"],
            "invalid": counts["invalid"], "record_ids": ids}


def quality_report(queue_dir: Path, approved: Path, provenance_dir: Path) -> dict:
    approved_rows = read_records(approved) if approved.is_file() else []
    queued_rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(queue_dir.glob("*.json"))] if queue_dir.exists() else []
    all_rows = approved_rows + queued_rows
    provenance = {}
    if provenance_dir.exists():
        for path in provenance_dir.glob("aic1-*.json"):
            provenance[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return {
        "approved": len(approved_rows), "pending": len(queued_rows),
        "labels": dict(Counter(r["label"] for r in approved_rows)),
        "policy_versions": dict(Counter(r.get("annotation_policy_version", "missing") for r in approved_rows)),
        "content_types_known": dict(Counter(provenance[r["record_id"]]["content_type"] for r in all_rows if r["record_id"] in provenance)),
        "provenance_missing": sum(r["record_id"] not in provenance for r in all_rows),
        "unique_event_groups": len({r["event_group_id"] for r in all_rows}),
        "duplicate_source_ids": sum(n - 1 for n in Counter(canonical_source(r["source_id"]) for r in all_rows).values() if n > 1),
        "note": "Historical records may lack provenance sidecars. The report does not change approved labels."
    }


def main():
    parser = argparse.ArgumentParser(description="Offline AIC-1 candidate batch import and dataset quality report")
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import")
    imp.add_argument("batch", type=Path)
    imp.add_argument("--topic", type=Path, default=Path("topics/taiwan_military_v2.json"))
    commands.add_parser("report")
    parser.add_argument("--queue-dir", type=Path, default=Path("data/review_queue"))
    parser.add_argument("--approved", type=Path, default=Path("data/labeled/pilot.jsonl"))
    parser.add_argument("--provenance-dir", type=Path, default=Path("data/provenance"))
    args = parser.parse_args()
    result = (import_batch(args.batch, args.topic, args.queue_dir, args.approved, args.provenance_dir)
              if args.command == "import" else quality_report(args.queue_dir, args.approved, args.provenance_dir))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
