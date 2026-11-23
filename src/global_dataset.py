"""Frozen global datasets from Phase 2M approvals ONLY. No classifier training."""
import argparse
from collections import Counter
from datetime import datetime
import os
from pathlib import Path
import random
import re

from .content_reference import load_source
from .global_feeds import REGIONS
from .global_io import (digest, document_hash, encoded, hash_string, keys, parse_json,
                        publish_directory, read_object, string, timestamp)
from .global_review import history, rights_status
from .global_sampling import diagnostics, load_sample

SPLITS = ("train", "validation", "test")
ALGORITHM = "aic-global-components-v1"


def _strings(values, name, nonempty=False):
    if not isinstance(values, list) or (nonempty and not values) or any(not isinstance(v, str) or not v.strip() for v in values) or len(values) != len(set(values)):
        raise ValueError(f"{name} requires unique nonempty strings")


def validate_cohort(cohort):
    keys(cohort, {"schema_version", "reviewed_by", "reviewed_at", "confirm_group_review", "items"}, "global cohort")
    if cohort["schema_version"] != "aic-global-cohort-v1" or cohort["confirm_group_review"] is not True:
        raise ValueError("Explicit human grouping review required")
    string(cohort["reviewed_by"], "group reviewer")
    timestamp(cohort["reviewed_at"], "group reviewed_at", utc=True)
    if not isinstance(cohort["items"], list) or not 1 <= len(cohort["items"]) <= 1000:
        raise ValueError("Cohort must contain 1-1000 selected global approvals")
    ids = set()
    for item in cohort["items"]:
        keys(item, {"source_ref_id", "approval_id", "event_group_ids", "duplicate_group_ids", "regions", "language", "sampling"}, "cohort item")
        _strings(item["event_group_ids"], "event_group_ids", nonempty=True)
        _strings(item["duplicate_group_ids"], "duplicate_group_ids")
        _strings(item["regions"], "regions", nonempty=True)
        if not set(item["regions"]).issubset(REGIONS):
            raise ValueError("Unknown human-reviewed region")
        if not isinstance(item["language"], str) or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]+)*|unknown", item["language"]):
            raise ValueError("Explicit reviewed language required")
        if not isinstance(item["source_ref_id"], str) or item["source_ref_id"] in ids:
            raise ValueError("Duplicate/invalid cohort source")
        ids.add(item["source_ref_id"])
    return cohort


def _sampling_evidence(item, ref, base):
    pointer = item["sampling"]
    if pointer is None:
        return None
    keys(pointer, {"path", "manifest_sha256", "candidate_id"}, "sampling evidence")
    string(pointer["path"], "sampling path")
    hash_string(pointer["manifest_sha256"], "sampling manifest hash")
    path = (base / pointer["path"]).resolve()
    if digest((path / "manifest.json").read_bytes()) != pointer["manifest_sha256"]:
        raise ValueError("Stale sampling evidence")
    manifest, selected = load_sample(path)
    matches = [r for r in selected if r["candidate_id"] == pointer["candidate_id"] and r["source_id"] == ref["canonical_source_id"]]
    if len(matches) != 1:
        raise ValueError("Cohort article was not in the selected review sample")
    ranked = matches[0]
    revision = ranked["ranking"]["article_revision"]
    if revision["basis"] == "registered_content":
        if revision["content_revision_sha256"] != ref["content_revision_sha256"]:
            raise ValueError("Sampled article content revision mismatch")
    elif revision["ranking_text_sha256"] != digest(ref["metadata"]["article_title"].strip().encode()):
        raise ValueError("Sampled title revision mismatch")
    return {"manifest_sha256": pointer["manifest_sha256"], "candidate_id": pointer["candidate_id"],
            "config": manifest["config"], "profile_sha256": manifest["profile_sha256"], "selection": ranked["sampling"]}


def build_rows(store, cohort, cohort_base):
    validate_cohort(cohort)
    approvals, heads = history(store)
    inventory = {ident: digest((Path(store) / "approvals" / ident / "approval.json").read_bytes()) for ident in sorted(approvals)}
    rows, documents, total_bytes = [], set(), 0
    for item in cohort["items"]:
        approval = approvals.get(item["approval_id"])
        if (approval is None or heads.get(approval["annotation_id"]) != item["approval_id"]
                or approval["source"]["source_ref_id"] != item["source_ref_id"]):
            raise ValueError("Missing, stale, non-current or mismatched global approval")
        ref, text, binding = load_source(store, item["source_ref_id"])
        if rights_status(store, item["source_ref_id"]) != "cleared":
            raise ValueError(f"Uncleared/restricted/conflicting rights: {item['source_ref_id']}")
        decision_dir = Path(store) / "rights" / item["source_ref_id"]
        decisions = sorted(decision_dir.iterdir())
        if len(decisions) != 1:
            raise ValueError("Exactly one current rights decision required")
        right_path = decisions[0] / "decision.json"
        annotation = approval["annotation"]
        documents.add((approval["taxonomy_sha256"], approval["annotation_policy_sha256"]))
        rows.append({"source_ref_id": item["source_ref_id"], "approval_id": item["approval_id"],
                     "approval_sha256": inventory[item["approval_id"]], "source_binding": binding,
                     "canonical_source_id": ref["canonical_source_id"], "content_revision_sha256": ref["content_revision_sha256"],
                     "duplicate_fingerprint": ref["duplicate_fingerprint"], "event_group_ids": item["event_group_ids"],
                     "duplicate_group_ids": item["duplicate_group_ids"], "regions": item["regions"], "language": item["language"],
                     "publisher": ref["metadata"]["publisher"], "published_at": ref["metadata"]["published_at"],
                     "collected_at": ref["metadata"]["collected_at"], "content_type": ref["metadata"]["content_type"],
                     "article_title": ref["metadata"]["article_title"], "article_text": text,
                     "annotation": annotation, "domains": annotation["domains"], "defense_event_types": annotation["defense_event_types"],
                     "task_label": "defense" if "defense" in annotation["domains"] else "nondefense",
                     "taxonomy_version": approval["taxonomy_version"], "taxonomy_sha256": approval["taxonomy_sha256"],
                     "annotation_policy_version": approval["annotation_policy_version"], "annotation_policy_sha256": approval["annotation_policy_sha256"],
                     "rights": {"decision_id": decisions[0].name, "sha256": digest(right_path.read_bytes()), "status": "cleared", "scope": "model_training"},
                     "sampling": _sampling_evidence(item, ref, Path(cohort_base))})
        total_bytes += len(encoded(rows[-1]))
        if total_bytes > 128 * 1024 * 1024:
            raise ValueError("Cohort content exceeds bounded pilot size (128 MiB)")
    if len(documents) != 1:
        raise ValueError("Mixed taxonomy/policy definitions require an explicit dataset migration")
    return sorted(rows, key=lambda r: r["source_ref_id"]), inventory


def leakage_keys(row):
    values = [(field, row[field]) for field in ("source_ref_id", "approval_id", "canonical_source_id", "content_revision_sha256", "duplicate_fingerprint")]
    values += [("event", value) for value in row["event_group_ids"]]
    values += [("duplicate", value) for value in row["duplicate_group_ids"]]
    return values


def components(rows):
    rows = sorted(rows, key=lambda r: r["source_ref_id"])
    parent, seen = list(range(len(rows))), {}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, row in enumerate(rows):
        for key in leakage_keys(row):
            if key in seen:
                parent[find(i)] = find(seen[key])
            seen[key] = i
    groups = {}
    for i, row in enumerate(rows):
        groups.setdefault(find(i), []).append(row)
    return list(groups.values())


def validate_partitions(parts):
    owners, records = {}, set()
    for name, rows in parts.items():
        for row in rows:
            if row["source_ref_id"] in records:
                raise ValueError("Duplicate record across/in splits")
            records.add(row["source_ref_id"])
            for key in leakage_keys(row):
                if key in owners and owners[key] != name:
                    raise ValueError(f"Cross-split leakage: {key[0]}")
                owners[key] = name


def split_rows(rows, seed):
    if type(seed) is not int:
        raise ValueError("Explicit integer split seed required")
    groups = components(rows)
    if len(rows) < 30:
        raise ValueError("Need at least 30 eligible global rows for split readiness; snapshot remains eligible")
    labels = ("defense", "nondefense")
    for label in labels:
        if sum(any(r["task_label"] == label for r in group) for group in groups) < 3:
            raise ValueError(f"Need 3 independent components containing {label}")
    random.Random(seed).shuffle(groups)
    groups.sort(key=len, reverse=True)
    parts, tallies = {s: [] for s in SPLITS}, {s: Counter() for s in SPLITS}
    totals = Counter(r["task_label"] for r in rows)
    targets = {s: {label: totals[label] * ratio for label in labels} for s, ratio in zip(SPLITS, (.7, .15, .15))}

    def assign(name, group):
        parts[name].extend(group)
        tallies[name].update(r["task_label"] for r in group)

    for name in SPLITS:
        while missing := {label for label in labels if not tallies[name][label]}:
            if not groups:
                raise ValueError("Cannot allocate independent class support")
            index = max(range(len(groups)), key=lambda i: len(missing & {r["task_label"] for r in groups[i]}))
            if not missing & {r["task_label"] for r in groups[index]}:
                raise ValueError("Cannot allocate independent class support")
            assign(name, groups.pop(index))
    for group in groups:
        counts = Counter(r["task_label"] for r in group)

        def delta(name):
            return sum(((tallies[name][label] + counts[label] - targets[name][label]) ** 2
                        - (tallies[name][label] - targets[name][label]) ** 2) / max(targets[name][label], 1) for label in labels)

        assign(min(SPLITS, key=delta), group)
    for rows in parts.values():
        rows.sort(key=lambda r: r["source_ref_id"])
    validate_partitions(parts)
    return parts


def stress_partitions(rows, publishers=None, cutoff=None):
    if cutoff is not None:
        timestamp(cutoff, "time cutoff")
    result = {"development": [], "holdout": [], "quarantine": []}
    for group in components(rows):
        flags = []
        for row in group:
            if publishers is not None:
                flags.append(row["publisher"] in publishers)
            elif row["published_at"] is None:
                flags.append(None)
            else:
                flags.append(datetime.fromisoformat(row["published_at"].replace("Z", "+00:00")) >= datetime.fromisoformat(cutoff.replace("Z", "+00:00")))
        chosen = "quarantine" if None in flags or len(set(flags)) != 1 else "holdout" if flags[0] else "development"
        result[chosen].extend(group)
    for part in result.values():
        part.sort(key=lambda r: r["source_ref_id"])
    validate_partitions(result)
    return result


def _payload(rows):
    return b"".join(encoded(r) + b"\n" for r in sorted(rows, key=lambda r: r["source_ref_id"]))


def _contents(rows, seed, publishers, cutoff):
    if type(seed) is not int:
        raise ValueError("Explicit integer split seed required")
    if publishers is not None:
        _strings(publishers, "publisher holdout", nonempty=True)
    if cutoff is not None:
        timestamp(cutoff, "time cutoff")
    files = {"snapshot.jsonl": _payload(rows)}
    readiness = {"snapshot_eligible": bool(rows), "supervised_split_ready": False, "training_supported": False}
    try:
        parts = split_rows(rows, seed)
    except ValueError as exc:
        readiness["split_readiness_reason"] = str(exc)
    else:
        readiness.update(supervised_split_ready=True, split_readiness_reason=None)
        files.update({f"{name}.jsonl": _payload(part) for name, part in parts.items()})
    stresses = {}
    for name, enabled, args in (("publisher", bool(publishers), {"publishers": publishers}), ("time", cutoff is not None, {"cutoff": cutoff})):
        if enabled:
            parts = stress_partitions(rows, **args)
            files.update({f"stress-{name}-{part}.jsonl": _payload(values) for part, values in parts.items()})
            stresses[name] = {"counts": {p: len(v) for p, v in parts.items()},
                              "both_classes_supported": all({r["task_label"] for r in parts[p]} == {"defense", "nondefense"} for p in ("development", "holdout")),
                              "quarantine_reason": "Mixed leakage components or missing publication dates",
                              "training_supported": False}
    return files, readiness, stresses


def export_dataset(store, cohort_path, output, seed=42, publisher_holdout=None, time_cutoff=None, require_splits=False):
    output, cohort_path, store = Path(output), Path(cohort_path).resolve(), Path(store).resolve()
    if output.exists():
        raise FileExistsError(output)
    cohort = read_object(cohort_path)
    rows, inventory = build_rows(store, cohort, cohort_path.parent)
    files, readiness, stress = _contents(rows, seed, publisher_holdout, time_cutoff)
    if require_splits and not readiness["supervised_split_ready"]:
        raise ValueError(readiness["split_readiness_reason"])
    if sum(map(len, files.values())) > 128 * 1024 * 1024:
        raise ValueError("Dataset bundle exceeds bounded pilot size (128 MiB)")
    files["cohort.json"] = encoded(cohort)
    manifest = {"schema_version": "aic-global-dataset-v1", "task": "defense_binary_v1", "algorithm": ALGORITHM, "seed": seed,
                "store_path": Path(os.path.relpath(store, output.resolve())).as_posix(),
                "cohort_source": {"path": Path(os.path.relpath(cohort_path, output.resolve())).as_posix(), "sha256": digest(cohort_path.read_bytes())},
                "approval_inventory": inventory, "files": {k: digest(v) for k, v in files.items()},
                "readiness": readiness, "coverage": diagnostics(rows, human=True),
                "stress_config": {"publishers": publisher_holdout, "time_cutoff": time_cutoff}, "stress_diagnostics": stress}
    manifest["manifest_id"] = document_hash(manifest)
    files["manifest.json"] = encoded(manifest)
    publish_directory(output, files)
    return manifest


def validate_dataset(directory):
    try:
        directory = Path(directory).resolve()
        manifest = read_object(directory / "manifest.json")
        keys(manifest, {"schema_version", "task", "algorithm", "seed", "store_path", "cohort_source", "approval_inventory",
                        "files", "readiness", "coverage", "stress_config", "stress_diagnostics", "manifest_id"}, "dataset manifest")
        if (manifest["schema_version"] != "aic-global-dataset-v1" or manifest["task"] != "defense_binary_v1"
                or manifest["algorithm"] != ALGORITHM or type(manifest["seed"]) is not int
                or manifest["manifest_id"] != document_hash({k: v for k, v in manifest.items() if k != "manifest_id"})):
            raise ValueError("Unsupported/tampered global manifest")
        cohort_path = (directory / manifest["cohort_source"]["path"]).resolve()
        if digest(cohort_path.read_bytes()) != manifest["cohort_source"]["sha256"]:
            raise ValueError("Stale authoritative cohort")
        cohort = read_object(cohort_path)
        rows, inventory = build_rows((directory / manifest["store_path"]).resolve(), cohort, cohort_path.parent)
        stress_config = manifest["stress_config"]
        files, readiness, stress = _contents(rows, manifest["seed"], stress_config["publishers"], stress_config["time_cutoff"])
        files["cohort.json"] = encoded(cohort)
        if (inventory != manifest["approval_inventory"] or readiness != manifest["readiness"]
                or stress != manifest["stress_diagnostics"] or diagnostics(rows, human=True) != manifest["coverage"]
                or {k: digest(v) for k, v in files.items()} != manifest["files"]):
            raise ValueError("Dataset identity, readiness or evidence mismatch")
        for name, expected in files.items():
            if (directory / name).read_bytes() != expected:
                raise ValueError(f"Frozen dataset contents mismatch: {name}")
        return manifest
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Global dataset validation failed: {exc}") from exc


def main():
    parser = argparse.ArgumentParser(description="Global approved dataset preparation; no training entry point")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--store", type=Path, default=Path("data/global_annotations"))
    export.add_argument("--cohort", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--seed", type=int, default=42)
    export.add_argument("--publisher-holdout", nargs="+")
    export.add_argument("--time-cutoff")
    export.add_argument("--require-splits", action="store_true")
    validate = commands.add_parser("validate")
    validate.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.command == "export":
        result = export_dataset(args.store, args.cohort, args.output, args.seed, args.publisher_holdout, args.time_cutoff, args.require_splits)
    else:
        result = validate_dataset(args.directory)
    print(encoded(result["readiness"]).decode())


if __name__ == "__main__":
    main()
