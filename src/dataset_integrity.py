"""AIC-1 Phase 2F: offline provenance and policy review, without rewriting gold records.

A rights attestation is metadata supplied by a human, not a legal determination.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .annotation_schema import validate_annotation
from .candidate_import import canonical_source, fingerprint
from .schema import LABELS, read_records, validate_record
from .topic_spec import read_topic_spec

KNOWN = {
    "aic1-0675e720018d49e1bf0aa3c09e1ea398": "reported_full_text",
    "aic1-1999a4ac12bc4272a1f2b6ee37e036e2": "reported_full_text",
    "aic1-dc3d9b392d6c446b86526ee4900af3cf": "reported_full_text",
    "aic1-9933f3f2046747048876b7cef00b17f7": "human_summary",
}
CONTENT_TYPES = {"reported_full_text", "licensed_full_text", "permitted_excerpt", "human_summary", "public_domain", "other_permitted"}
RIGHTS = {"unverified", "cleared", "restricted"}


def write_new(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as out:
        json.dump(payload, out, ensure_ascii=False, indent=2, sort_keys=True)
        out.write("\n")


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected object: {path}")
    return value


def backfill(approved: Path, provenance_dir: Path) -> dict:
    """Create missing sidecars only. Unknown content type is explicit, never guessed."""
    created, preserved = [], []
    for row in read_records(approved):
        ident = row["record_id"]
        target = provenance_dir / f"{ident}.json"
        if target.exists():
            preserved.append(ident)
            continue
        payload = {
            "record_id": ident,
            "source_id": row["source_id"],
            "canonical_source_id": canonical_source(row["source_id"]),
            "text_sha256": fingerprint(row["article_text"]),
            "content_type": KNOWN.get(ident, "unknown_needs_review"),
            "rights_status": "unverified",
            "rights_note": "Historical backfill: rights and source content not independently verified",
            "provenance_method": "historical_metadata_backfill",
        }
        write_new(target, payload)
        created.append(ident)
    return {"created": len(created), "preserved": len(preserved), "new_record_ids": created}


def attest_rights(record_id: str, rights_status: str, evidence: str, content_type: str,
                  approver: str, approved: Path, provenance_dir: Path) -> dict:
    """Append-only rights decisions, never overwrite historical provenance or approval."""
    if rights_status not in RIGHTS or content_type not in CONTENT_TYPES:
        raise ValueError("Invalid rights status or content type")
    if not evidence.strip() or not approver.strip():
        raise ValueError("Evidence and approver are required")
    if not any(r["record_id"] == record_id for r in read_records(approved)):
        raise ValueError("Unknown approved record")
    if not (provenance_dir / f"{record_id}.json").exists():
        raise ValueError("Backfill provenance first")
    decision = {"record_id": record_id, "rights_status": rights_status,
                "content_type": content_type, "rights_note": evidence.strip(),
                "attested_by": approver.strip(), "attested_at": datetime.now(timezone.utc).isoformat()}
    decisions = provenance_dir / "rights_decisions"
    write_new(decisions / f"{record_id}-{uuid4().hex}.json", decision)
    return decision


def effective_provenance(record_id: str, provenance_dir: Path) -> dict | None:
    path = provenance_dir / f"{record_id}.json"
    if not path.exists():
        return None
    base = read_json(path)
    decisions = list((provenance_dir / "rights_decisions").glob(f"{record_id}-*.json"))
    if decisions:
        # Multiple contradictory status changes require manual reconciliation, not implicit latest-wins.
        if len(decisions) != 1:
            return {**base, "rights_status": "conflicting_decisions"}
        return {**base, **read_json(decisions[0])}
    return base


def submit_policy_review(record_id: str, review_file: Path, approved: Path,
                         topic_file: Path, reviews_dir: Path, reviewer: str,
                         confirm: bool) -> dict:
    if not confirm or not reviewer.strip():
        raise ValueError("Human confirmation and reviewer identifier are required")
    row = next((r for r in read_records(approved) if r["record_id"] == record_id), None)
    if row is None:
        raise ValueError("Unknown approved record")
    spec = read_topic_spec(topic_file)
    if row.get("topic_id") != spec["topic_id"]:
        raise ValueError("Topic mismatch")
    proposed = read_json(review_file)
    if set(proposed) != {"label", "rationale", "criteria"}:
        raise ValueError("Review must contain label, rationale, criteria")
    # Evaluate a copy against the original required fields and the NEW policy.
    revision = {**row, **proposed, "annotation_policy_version": spec["policy_version"]}
    validate_record(revision, 1)
    if proposed["label"] not in LABELS:
        raise ValueError("Invalid label")
    artifact = {"record_id": record_id, "source_record_hash": hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                "source_policy_version": row.get("annotation_policy_version"),
                "target_policy_version": spec["policy_version"],
                "reviewed_by": reviewer.strip(), "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "label": proposed["label"], "rationale": proposed["rationale"],
                "criteria": proposed["criteria"]}
    target = reviews_dir / f"{record_id}__{spec['policy_version']}.json"
    write_new(target, artifact)
    return artifact


def snapshot_report(approved: Path, provenance_dir: Path, reviews_dir: Path,
                    topic_file: Path) -> tuple[dict, list[dict]]:
    spec = read_topic_spec(topic_file)
    included = []
    blocked = {}
    for row in read_records(approved):
        reasons = []
        prov = effective_provenance(row["record_id"], provenance_dir)
        if prov is None:
            reasons.append("missing_provenance")
        else:
            if prov.get("rights_status") != "cleared":
                reasons.append("rights_not_cleared")
            if prov.get("content_type") not in CONTENT_TYPES:
                reasons.append("unknown_content_type")
            if prov.get("canonical_source_id") != canonical_source(row["source_id"]) or prov.get("text_sha256") != fingerprint(row["article_text"]):
                reasons.append("provenance_content_mismatch")
        if row.get("topic_id") != spec["topic_id"]:
            reasons.append("topic_mismatch")
        new_row = dict(row)
        if row.get("annotation_policy_version") != spec["policy_version"]:
            review = reviews_dir / f"{row['record_id']}__{spec['policy_version']}.json"
            if not review.is_file():
                reasons.append("policy_review_missing")
            else:
                rev = read_json(review)
                expected_hash = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                if rev.get("source_record_hash") != expected_hash or rev.get("target_policy_version") != spec["policy_version"]:
                    reasons.append("stale_policy_review")
                else:
                    new_row.update({k: rev[k] for k in ("label", "rationale", "criteria")})
                    new_row["annotation_policy_version"] = spec["policy_version"]
                    new_row["annotation_version"] = row["annotation_version"] + "+policy_review"
                    validate_record(new_row, 1)
        if reasons:
            blocked[row["record_id"]] = reasons
        else:
            included.append(new_row)
    groups = Counter(x["event_group_id"] for x in included)
    counts = Counter(x["label"] for x in included)
    report = {"target_policy": spec["policy_version"], "approved_total": len(read_records(approved)),
              "eligible": len(included), "blocked": blocked, "label_counts": dict(counts),
              "unique_eligible_event_groups": len(groups), "training_ready": len(included) >= 20 and all(counts[c] >= 3 for c in LABELS) and len(groups) >= 10}
    return report, included


def freeze_snapshot(report: dict, rows: list[dict], output_dir: Path) -> Path:
    if not report["training_ready"]:
        raise ValueError("Dataset not ready: minimum 20 eligible, 3 per class, 10 event groups")
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in sorted(rows, key=lambda x: x["record_id"]))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    path = output_dir / f"aic1-{report['target_policy']}-{digest[:12]}.jsonl"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload)
    write_new(path.with_suffix(".manifest.json"), {**report, "sha256": digest, "records": len(rows), "event_group_splitting_required": True})
    return path


def main() -> None:
    p = argparse.ArgumentParser(description="Offline AIC-1 dataset integrity tools")
    p.add_argument("--approved", type=Path, default=Path("data/labeled/pilot.jsonl"))
    p.add_argument("--provenance-dir", type=Path, default=Path("data/provenance"))
    p.add_argument("--reviews-dir", type=Path, default=Path("data/policy_reviews"))
    p.add_argument("--topic", type=Path, default=Path("topics/taiwan_military_v2.json"))
    c = p.add_subparsers(dest="command", required=True)
    c.add_parser("backfill")
    c.add_parser("report")
    r = c.add_parser("review")
    r.add_argument("record_id")
    r.add_argument("review_file", type=Path)
    r.add_argument("--reviewer", required=True)
    r.add_argument("--confirm-human-review", action="store_true")
    a = c.add_parser("rights")
    a.add_argument("record_id")
    a.add_argument("--status", choices=sorted(RIGHTS), required=True)
    a.add_argument("--content-type", choices=sorted(CONTENT_TYPES), required=True)
    a.add_argument("--evidence", required=True)
    a.add_argument("--reviewer", required=True)
    s = c.add_parser("snapshot")
    s.add_argument("--output-dir", type=Path, default=Path("data/snapshots"))
    s.add_argument("--write", action="store_true")
    args = p.parse_args()
    if args.command == "backfill":
        result = backfill(args.approved, args.provenance_dir)
    elif args.command == "rights":
        result = attest_rights(args.record_id, args.status, args.evidence, args.content_type,
                               args.reviewer, args.approved, args.provenance_dir)
    elif args.command == "review":
        result = submit_policy_review(args.record_id, args.review_file, args.approved,
                                      args.topic, args.reviews_dir, args.reviewer,
                                      args.confirm_human_review)
    else:
        report, rows = snapshot_report(args.approved, args.provenance_dir, args.reviews_dir, args.topic)
        result = report
        if args.command == "snapshot" and args.write:
            result = {**report, "snapshot_file": str(freeze_snapshot(report, rows, args.output_dir))}
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
