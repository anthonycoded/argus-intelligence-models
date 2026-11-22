import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from .schema import LABELS, counts, read_records


def split_grouped(rows: list[dict], seed=42):
    """Event-group split. Approximate 70/15/15, never split one event."""
    groups = defaultdict(list)
    for row in rows:
        groups[row["event_group_id"]].append(row)
    if len(rows) < 30:
        raise ValueError("Need at least 30 human-verified rows for a basic split sanity check")
    for label in LABELS:
        n = sum(any(r["label"] == label for r in g) for g in groups.values())
        if n < 3:
            raise ValueError(f"Need at least 3 distinct event groups containing {label}; got {n}")
    rng = random.Random(seed)
    keys = sorted(groups)
    rng.shuffle(keys)
    # Greedy per-label event-group balancing; no perfect stratification is promised.
    targets = {s: {l: counts(rows)[l] * f for l in LABELS}
               for s, f in (("train", .70), ("validation", .15), ("test", .15))}
    parts = {s: [] for s in targets}
    tallies = {s: {l: 0 for l in LABELS} for s in targets}
    # Seed one group per split first; optimize label targets for remaining groups.
    for i, key in enumerate(keys):
        group = groups[key]
        group_counts = counts(group)
        if i < 3:
            chosen = ("train", "validation", "test")[i]
        else:
            def cost(split):
                return sum(((tallies[split][l] + group_counts[l] - targets[split][l]) / max(targets[split][l], 1)) ** 2
                           for l in LABELS) + 0.002 * len(parts[split])
            chosen = min(targets, key=cost)
        parts[chosen].extend(group)
        for label in LABELS:
            tallies[chosen][label] += group_counts[label]
    return parts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("data/splits"))
    args = p.parse_args()
    parts = split_grouped(read_records(args.input))
    args.out.mkdir(parents=True, exist_ok=True)
    for split, rows in parts.items():
        (args.out / f"{split}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        print(f"{split}: {len(rows)} rows, {counts(rows)}")
    print("Check split sizes and class counts before training. Preserve held-out test data.")


if __name__ == "__main__":
    main()
