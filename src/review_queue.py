"""Local, explicitly human-reviewed intake queue for AIC-1 pilot annotations.

No network access, LLM labeling, or Argus-Core database connectivity.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .schema import read_records, validate_record
from .topic_spec import read_topic_spec

INPUT_FIELDS = ("event_group_id", "source_id", "collected_at", "article_title", "article_text")
REVIEW_FIELDS = ("label", "rationale", "criteria")


def _object(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(obj, dict):
        raise ValueError(f"{path}: expected JSON object")
    return obj


def _write_new(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(obj, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _subject_spec(topic: dict) -> str:
    return (
        f"Mandatory subject: {topic['mandatory_subject']} "
        f"Geography: {topic['geographic_scope']} "
        f"Material connection: {topic['material_connection']} "
        f"Exclusions: {'; '.join(topic['exclusions'])}"
    )


def add_article(input_path: Path, topic_path: Path, queue_dir: Path, approved_path: Path) -> str:
    article = _object(input_path)
    if set(article) != set(INPUT_FIELDS):
        raise ValueError(f"Article input must contain exactly {INPUT_FIELDS}")
    if any(not isinstance(article[key], str) or not article[key].strip() for key in INPUT_FIELDS):
        raise ValueError("All article input fields must be nonempty strings")
    try:
        dt = datetime.fromisoformat(article["collected_at"].replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError as exc:
        raise ValueError("collected_at must be an ISO-8601 timestamp with timezone") from exc
    topic = read_topic_spec(topic_path)
    # Prevent duplicate source/topic pairs from being included twice.
    existing = [ _object(path) for path in queue_dir.glob("*.json") ] if queue_dir.exists() else []
    if approved_path.exists():
        existing += read_records(approved_path)
    if any(r["source_id"] == article["source_id"] and r["topic"] == topic["title"] for r in existing):
        raise ValueError("Duplicate source_id for this topic")
    record_id = f"aic1-{uuid4().hex}"
    pending = {
        "record_id": record_id,
        **article,
        "topic": topic["title"],
        "subject_spec": _subject_spec(topic),
        "topic_id": topic["topic_id"],
        "topic_policy_version": topic["policy_version"],
        "review_status": "pending",
    }
    _write_new(queue_dir / f"{record_id}.json", pending)
    return record_id


def approve_article(record_id: str, review_path: Path, queue_dir: Path,
                    approved_path: Path, confirm_human_review: bool = False) -> dict:
    if not confirm_human_review:
        raise ValueError("Explicit --confirm-human-review is required; no automatic approval")
    if not record_id.startswith("aic1-") or len(record_id) != 37 or not all(c in '0123456789abcdef' for c in record_id[5:]):
        raise ValueError("Invalid record ID")
    pending_path = queue_dir / f"{record_id}.json"
    pending = _object(pending_path)
    if pending.get("record_id") != record_id or pending.get("review_status") != "pending":
        raise ValueError("Invalid pending record")
    review = _object(review_path)
    if set(review) != set(REVIEW_FIELDS):
        raise ValueError(f"Review must contain exactly {REVIEW_FIELDS}")
    row = {key: value for key, value in pending.items() if key != "review_status"}
    row.update(review)
    row.update({
        "label_source": "human_verified",
        "annotation_version": "v1.1",
        "annotation_policy_version": pending["topic_policy_version"],
    })
    validate_record(row, 1)
    if "criteria" not in row:
        raise ValueError("Phase 2C requires structured criteria")
    approved_path.parent.mkdir(parents=True, exist_ok=True)
    rows = read_records(approved_path) if approved_path.exists() else []
    if any(r["record_id"] == record_id for r in rows):
        raise ValueError("Record already approved")
    if any(r["source_id"] == row["source_id"] and r["topic"] == row["topic"] for r in rows):
        raise ValueError("Duplicate source/topic pair in approved dataset")
    # Atomically replace the small local pilot file; single-writer CLI only.
    temp = approved_path.with_name(f".{approved_path.name}.{uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            for r in [*rows, row]:
                handle.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(temp, approved_path)
    finally:
        temp.unlink(missing_ok=True)
    pending_path.unlink()
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="Local AIC-1 human annotation queue")
    parser.add_argument("--queue-dir", type=Path, default=Path("data/review_queue"))
    parser.add_argument("--approved", type=Path, default=Path("data/labeled/pilot.jsonl"))
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("add")
    ingest.add_argument("article", type=Path)
    ingest.add_argument("--topic", type=Path, default=Path("topics/taiwan_military_v1.json"))
    commands.add_parser("list")
    approve = commands.add_parser("approve")
    approve.add_argument("record_id")
    approve.add_argument("review", type=Path)
    approve.add_argument("--confirm-human-review", action="store_true")
    args = parser.parse_args()
    if args.command == "add":
        key = add_article(args.article, args.topic, args.queue_dir, args.approved)
        print(f"Queued for human review: {key}")
        print(f"Review queue file: {args.queue_dir / (key + '.json')}")
    elif args.command == "list":
        paths = sorted(args.queue_dir.glob("*.json")) if args.queue_dir.exists() else []
        for path in paths:
            item = _object(path)
            print(f"{item['record_id']} | {item['article_title']}")
        print(f"Pending: {len(paths)}")
    elif args.command == "approve":
        row = approve_article(args.record_id, args.review, args.queue_dir, args.approved,
                              args.confirm_human_review)
        print(f"Approved human-reviewed record: {row['record_id']} ({row['label']})")
        print(f"Dataset: {args.approved}")


if __name__ == "__main__":
    main()
