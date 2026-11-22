"""Explicitly update the pinned topic policy for one PENDING AIC-1 record.

This command never changes an approved record, its label, or its article text.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from .topic_spec import read_topic_spec


def retarget_pending(record_id: str, topic_path: Path, queue_dir: Path, confirm: bool = False) -> dict:
    if not confirm:
        raise ValueError("--confirm-policy-change is required")
    if not record_id.startswith("aic1-") or len(record_id) != 37 or any(c not in "0123456789abcdef" for c in record_id[5:]):
        raise ValueError("Invalid record ID")
    pending_path = queue_dir / f"{record_id}.json"
    pending = json.loads(pending_path.read_text(encoding="utf-8-sig"))
    if pending.get("record_id") != record_id or pending.get("review_status") != "pending":
        raise ValueError("Only matching pending records can change policy")
    topic = read_topic_spec(topic_path)
    if pending.get("topic_id") != topic["topic_id"] or pending.get("topic") != topic["title"]:
        raise ValueError("Policy topic ID/title mismatch")
    old_version = pending["topic_policy_version"]
    if old_version == topic["policy_version"]:
        raise ValueError("Record already uses that policy version")
    pending["policy_change_history"] = [
        *pending.get("policy_change_history", []),
        {"from": old_version, "to": topic["policy_version"]}
    ]
    pending["topic_policy_version"] = topic["policy_version"]
    pending["subject_spec"] = (
        f"Mandatory subject: {topic['mandatory_subject']} "
        f"Geography: {topic['geographic_scope']} "
        f"Material connection: {topic['material_connection']} "
        f"Exclusions: {'; '.join(topic['exclusions'])}"
    )
    temp = pending_path.with_name(f".{record_id}.{uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(pending, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp, pending_path)
    finally:
        temp.unlink(missing_ok=True)
    return pending


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-pin pending AIC-1 record to a reviewed topic policy")
    parser.add_argument("record_id")
    parser.add_argument("--topic", type=Path, required=True)
    parser.add_argument("--queue-dir", type=Path, default=Path("data/review_queue"))
    parser.add_argument("--confirm-policy-change", action="store_true")
    args = parser.parse_args()
    updated = retarget_pending(args.record_id, args.topic, args.queue_dir, args.confirm_policy_change)
    print(f"Pending record {updated['record_id']} now uses {updated['topic_policy_version']}")
    print("Article remains pending; no label assigned or approved.")


if __name__ == "__main__":
    main()
