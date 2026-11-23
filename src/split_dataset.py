"""Deterministic leakage-component allocation; CLI accepts frozen snapshots only."""
import argparse
import random
from collections import Counter
from pathlib import Path

from .candidate_import import canonical_source, fingerprint
from .schema import LABELS, counts, validate_record

SPLITS = ("train", "validation", "test")
RATIOS = (.70, .15, .15)


def leakage_keys(row):
    keys = [("record", row["record_id"]), ("event", row["event_group_id"]),
            ("source", canonical_source(row["source_id"])),
            ("content", fingerprint(row["article_text"]))]
    for field in ("duplicate_group_id", "known_duplicate_group_id"):
        if field in row:
            if not isinstance(row[field], str) or not row[field].strip():
                raise ValueError(f"{field} must be a nonempty string")
            keys.append(("duplicate", row[field]))
    return keys


def leakage_components(rows):
    """Union transitive event, source, content and explicitly known duplicates."""
    rows = sorted(rows, key=lambda r: r["record_id"])
    parents = list(range(len(rows)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    seen, ids = {}, set()
    for i, row in enumerate(rows):
        validate_record(row, i + 1)
        if row["record_id"] in ids:
            raise ValueError(f"Duplicate record_id: {row['record_id']}")
        ids.add(row["record_id"])
        for key in leakage_keys(row):
            if key in seen:
                parents[root(i)] = root(seen[key])
            seen[key] = i
    groups = {}
    for i, row in enumerate(rows):
        groups.setdefault(root(i), []).append(row)
    return list(groups.values())


def validate_partitions(parts):
    if set(parts) != set(SPLITS):
        raise ValueError("Exactly train, validation and test splits are required")
    owners = {}
    for name in SPLITS:
        if not parts[name] or any(counts(parts[name])[label] == 0 for label in LABELS):
            raise ValueError(f"{name}: every label requires support; collect more independent groups")
        for i, row in enumerate(parts[name], 1):
            validate_record(row, i)
            for key in leakage_keys(row):
                if key in owners and (owners[key] != name or key[0] == "record"):
                    raise ValueError(f"Split leakage/duplicate {key[0]}: {key[1]}")
                owners[key] = name
    if sum(map(len, parts.values())) < 30:
        raise ValueError("Need at least 30 eligible rows for training/evaluation readiness")


def split_grouped(rows: list[dict], seed=42):
    """Approximate 70/15/15 by indivisible leakage components, with class support."""
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    groups = leakage_components(rows)
    if len(rows) < 30:
        raise ValueError("Need at least 30 eligible rows for a basic split sanity check")
    for label in LABELS:
        n = sum(any(r["label"] == label for r in g) for g in groups)
        if n < 3:
            raise ValueError(f"Need at least 3 independent leakage groups containing {label}; got {n}")
    random.Random(seed).shuffle(groups)
    groups.sort(key=len, reverse=True)
    totals = counts(rows)
    targets = {s: {l: totals[l] * ratio for l in LABELS} for s, ratio in zip(SPLITS, RATIOS)}
    parts = {s: [] for s in SPLITS}
    tallies = {s: Counter() for s in SPLITS}

    def assign(name, group):
        parts[name].extend(group)
        tallies[name].update(r["label"] for r in group)

    # Reserve support in each split before optimizing sizes.
    for name in SPLITS:
        while missing := {l for l in LABELS if not tallies[name][l]}:
            if not groups:
                raise ValueError("Cannot allocate class support; collect more independent groups")
            index = max(range(len(groups)), key=lambda i: len(missing & {r["label"] for r in groups[i]}))
            if not missing & {r["label"] for r in groups[index]}:
                raise ValueError("Cannot allocate class support; collect more independent groups")
            assign(name, groups.pop(index))
    for group in groups:
        gc = counts(group)

        def delta(name):
            # Change in GLOBAL squared allocation error, not destination error.
            return sum(((tallies[name][l] + gc[l] - targets[name][l]) ** 2
                        - (tallies[name][l] - targets[name][l]) ** 2)
                       / max(targets[name][l], 1) for l in LABELS)

        assign(min(SPLITS, key=delta), group)
    for part in parts.values():
        part.sort(key=lambda r: r["record_id"])
    validate_partitions(parts)
    return parts


def main():
    p = argparse.ArgumentParser(description="Split an eligible frozen snapshot; legacy raw inputs are refused")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True, help="Phase 2L snapshot manifest")
    p.add_argument("--out", type=Path, default=Path("data/splits"))
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    from .training_manifest import freeze_splits
    print(f"Frozen splits: {freeze_splits(args.input, args.manifest, args.out, args.seed)}")


if __name__ == "__main__":
    main()
