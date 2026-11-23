"""Phase 2L: frozen, locally verifiable eligibility and split manifests.

Hashes detect drift, not forgery by someone able to rewrite the approval store.
Authoritative local evidence stays available and is checked again before training,
including the current rights-decision inventory (new restrictions fail closed).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from .candidate_import import canonical_source, fingerprint
from .dataset_integrity import CONTENT_TYPES, snapshot_report
from .review_queue import _subject_spec
from .schema import read_records, validate_record
from .split_dataset import SPLITS, split_grouped, validate_partitions
from .topic_spec import read_topic_spec


def record_hash(row):
    # Same serialization as existing policy-review source_record_hash.
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pairs(items):
    obj = {}
    for key, value in items:
        if key in obj:
            raise ValueError(f"Duplicate JSON key: {key}")
        obj[key] = value
    return obj


def _object(path):
    def invalid(value):
        raise ValueError(f"Invalid JSON constant: {value}")
    obj = json.loads(Path(path).read_text(encoding="utf-8-sig"),
                     object_pairs_hook=_pairs, parse_constant=invalid)
    if not isinstance(obj, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return obj


def _timestamp(value, field):
    if not isinstance(value, str) or datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError(f"{field} requires a timezone-aware timestamp")


def _nonempty(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty")


def _slug(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError("Unsafe record/policy identifier")
    return value


def _relative(path, base):
    return Path(os.path.relpath(Path(path).resolve(), Path(base).resolve())).as_posix()


def _ref(path, base):
    path = Path(path).resolve()
    return {"path": _relative(path, base), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _check_ref(ref, base):
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise ValueError("Malformed file reference")
    _nonempty(ref["path"], "reference path")
    if not isinstance(ref["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", ref["sha256"]):
        raise ValueError("Malformed SHA-256")
    path = (base / ref["path"]).resolve()
    if _ref(path, base) != ref:
        raise ValueError(f"Manifest file/hash mismatch: {path}")
    return path


def _eligible_row(row, spec, provenance_dir, reviews_dir, base):
    """Validate actual evidence; a boolean eligibility assertion is insufficient."""
    validate_record(row, 1)
    ident = _slug(row["record_id"])
    if "criteria" not in row or row.get("topic_id") != spec["topic_id"] or row["topic"] != spec["title"]:
        raise ValueError(f"{ident}: structured approval/topic identity required")
    prov_path = provenance_dir / f"{ident}.json"
    prov = _object(prov_path)
    if (prov.get("record_id") != ident
            or prov.get("canonical_source_id") != canonical_source(row["source_id"])
            or prov.get("text_sha256") != fingerprint(row["article_text"])):
        raise ValueError(f"{ident}: provenance identity/content mismatch")
    if "source_id" in prov and canonical_source(prov["source_id"]) != canonical_source(row["source_id"]):
        raise ValueError(f"{ident}: provenance source mismatch")
    decisions = sorted((provenance_dir / "rights_decisions").glob(f"{ident}-*.json"))
    if len(decisions) != 1:
        raise ValueError(f"{ident}: exactly one explicit rights decision required; missing/conflicting decisions")
    decision = _object(decisions[0])
    if (decision.get("record_id") != ident or decision.get("rights_status") != "cleared"
            or decision.get("content_type") not in CONTENT_TYPES
            or decision.get("source_record_hash") != record_hash(row)
            or decision.get("content_sha256") != text_hash(row["article_text"])
            or decision.get("canonical_source_id") != canonical_source(row["source_id"])
            or decision.get("provenance_sha256") != _ref(prov_path, base)["sha256"]):
        raise ValueError(f"{ident}: rights not cleared or rights identity/content mismatch")
    # A restriction in the base cannot be overridden by a cleared sidecar.
    if prov.get("rights_status") not in (None, "unverified", "cleared"):
        raise ValueError(f"{ident}: restricted/conflicting provenance")
    for key in ("attested_by", "rights_note"):
        _nonempty(decision.get(key), key)
    _timestamp(decision.get("attested_at"), "attested_at")
    result = dict(row)
    review_ref = None
    if row.get("annotation_policy_version") != spec["policy_version"]:
        review_path = reviews_dir / f"{ident}__{_slug(spec['policy_version'])}.json"
        review = _object(review_path)
        if (review.get("record_id") != ident or review.get("source_record_hash") != record_hash(row)
                or review.get("source_policy_version") != row.get("annotation_policy_version")
                or review.get("target_policy_version") != spec["policy_version"]):
            raise ValueError(f"{ident}: stale/mismatched policy review")
        _nonempty(review.get("reviewed_by"), "reviewed_by")
        _timestamp(review.get("reviewed_at"), "reviewed_at")
        for key in ("label", "rationale", "criteria"):
            result[key] = review[key]
        result["annotation_policy_version"] = spec["policy_version"]
        result["annotation_version"] += "+policy_review"
        review_ref = _ref(review_path, base)
    # Training requirements must describe the policy used by the derived label.
    result["subject_spec"] = _subject_spec(spec)
    validate_record(result, 1)
    return result, {"source_record_hash": record_hash(row), "content_sha256": text_hash(row["article_text"]),
                    "provenance": _ref(prov_path, base), "rights": _ref(decisions[0], base),
                    "policy_review": review_ref}


def _payload(rows):
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                   for r in sorted(rows, key=lambda r: r["record_id"]))


def create_snapshot(approved, provenance_dir, reviews_dir, topic, output_dir):
    """Freeze any nonempty eligible subset; training readiness is a later check.

    Output is a NEW directory. Publication uses rename after all files are written.
    """
    approved, provenance_dir, reviews_dir, topic, output_dir = map(
        Path, (approved, provenance_dir, reviews_dir, topic, output_dir))
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite snapshot directory: {output_dir}")
    report, candidates = snapshot_report(approved, provenance_dir, reviews_dir, topic)
    if not candidates:
        raise ValueError(f"No eligible records to snapshot; rights/policy approval required: {report['blocked']}")
    spec = read_topic_spec(topic)
    originals = {r["record_id"]: r for r in read_records(approved)}
    rows, evidence = [], {}
    for candidate in candidates:
        row, proof = _eligible_row(originals[candidate["record_id"]], spec, provenance_dir, reviews_dir, output_dir)
        rows.append(row)
        evidence[row["record_id"]] = proof
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".aic1-snapshot-", dir=output_dir.parent) as temp:
        stage = Path(temp) / "bundle"
        stage.mkdir()
        data = stage / "snapshot.jsonl"
        data.write_bytes(_payload(rows).encode("utf-8"))
        manifest = {"schema_version": 1, "kind": "aic1-eligible-snapshot",
                    "approved": _ref(approved, output_dir), "topic": _ref(topic, output_dir),
                    "provenance_dir": _relative(provenance_dir, output_dir),
                    "reviews_dir": _relative(reviews_dir, output_dir),
                    "snapshot": {"path": "snapshot.jsonl", "sha256": hashlib.sha256(data.read_bytes()).hexdigest()},
                    "evidence": evidence}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        # Single-writer workflow; never replace a pre-existing directory.
        if output_dir.exists():
            raise FileExistsError(output_dir)
        stage.rename(output_dir)
    return output_dir / "manifest.json"


def _validate_snapshot(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    base = manifest_path.parent
    obj = _object(manifest_path)
    required = {"schema_version", "kind", "approved", "topic", "provenance_dir", "reviews_dir", "snapshot", "evidence"}
    if set(obj) != required or type(obj["schema_version"]) is not int or obj["schema_version"] != 1 or obj["kind"] != "aic1-eligible-snapshot":
        raise ValueError("Unsupported/malformed frozen snapshot manifest; regenerate legacy snapshots")
    approved = _check_ref(obj["approved"], base)
    topic = _check_ref(obj["topic"], base)
    data = _check_ref(obj["snapshot"], base)
    for field in ("provenance_dir", "reviews_dir"):
        _nonempty(obj[field], field)
    prov, reviews = (base / obj["provenance_dir"]).resolve(), (base / obj["reviews_dir"]).resolve()
    spec = read_topic_spec(topic)
    originals = {r["record_id"]: r for r in read_records(approved)}
    rows = read_records(data)
    if not rows or not isinstance(obj["evidence"], dict) or set(obj["evidence"]) != {r["record_id"] for r in rows}:
        raise ValueError("Snapshot/evidence membership mismatch or empty snapshot")
    for row in rows:
        if row["record_id"] not in originals:
            raise ValueError("Snapshot annotation not in approved store")
        expected, proof = _eligible_row(originals[row["record_id"]], spec, prov, reviews, base)
        if row != expected or obj["evidence"][row["record_id"]] != proof:
            raise ValueError("Snapshot annotation/evidence identity mismatch")
    return rows, data


def validate_snapshot(manifest_path):
    try:
        return _validate_snapshot(manifest_path)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError(f"Frozen snapshot validation failed: {exc}") from exc


def freeze_splits(snapshot_path, snapshot_manifest, output_dir, seed=42):
    rows, actual = validate_snapshot(snapshot_manifest)
    if actual != Path(snapshot_path).resolve():
        raise ValueError("Input does not match frozen snapshot manifest")
    parts = split_grouped(rows, seed)
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite split directory: {output_dir}; choose a new directory")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".aic1-splits-", dir=output_dir.parent) as temp:
        stage = Path(temp) / "bundle"
        stage.mkdir()
        refs = {}
        for name in SPLITS:
            path = stage / f"{name}.jsonl"
            path.write_bytes(_payload(parts[name]).encode("utf-8"))
            refs[name] = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        manifest = {"schema_version": 1, "kind": "aic1-training-splits", "seed": seed,
                    "split_algorithm": "aic1-leakage-v1",
                    "snapshot_manifest": _ref(snapshot_manifest, output_dir), "splits": refs}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if output_dir.exists():
            raise FileExistsError(output_dir)
        stage.rename(output_dir)
    return output_dir / "manifest.json"


def _validate_training_manifest(manifest_path, data_dir):
    manifest_path, data_dir = Path(manifest_path).resolve(), Path(data_dir).resolve()
    obj = _object(manifest_path)
    if (set(obj) != {"schema_version", "kind", "seed", "split_algorithm", "snapshot_manifest", "splits"}
            or type(obj["schema_version"]) is not int or obj["schema_version"] != 1
            or obj["kind"] != "aic1-training-splits" or type(obj["seed"]) is not int
            or obj["split_algorithm"] != "aic1-leakage-v1"
            or not isinstance(obj["splits"], dict) or set(obj["splits"]) != set(SPLITS)):
        raise ValueError("Unsupported/malformed training manifest")
    snapshot = _check_ref(obj["snapshot_manifest"], manifest_path.parent)
    rows, _ = validate_snapshot(snapshot)
    parts = {}
    for name in SPLITS:
        path = _check_ref(obj["splits"][name], manifest_path.parent)
        if path != data_dir / f"{name}.jsonl":
            raise ValueError(f"{name}: manifest/data path mismatch")
        parts[name] = read_records(path)
    validate_partitions(parts)
    actual = [r for name in SPLITS for r in parts[name]]
    if _payload(actual) != _payload(rows):
        raise ValueError("Split membership/annotation differs from eligible frozen snapshot")
    if parts != split_grouped(rows, obj["seed"]):
        raise ValueError("Split allocation differs from frozen seed/algorithm")
    return parts


def validate_training_manifest(manifest_path, data_dir):
    try:
        return _validate_training_manifest(manifest_path, data_dir)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError(f"Training manifest validation failed: {exc}") from exc
