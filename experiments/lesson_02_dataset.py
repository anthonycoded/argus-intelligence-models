
import json
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "aic1_synthetic_v2"

def load_jsonl(path):
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

records = load_jsonl(DATA_DIR / "aic1_synthetic_v2.jsonl")
split_rows = load_jsonl(DATA_DIR / "group_splits.jsonl")

# Map each scenario group to its assigned split
splits = {
    row["group_id"]: row["split"]
    for row in split_rows
}

# Convert string labels into numeric labels
label_to_id = {
    "nondefense": 0,
    "defense": 1,
}

for record in records:
    record["label_id"] = label_to_id[record["fixture_target"]]
    record["split"] = splits[record["group_id"]]

# Separate the records
train_records = [r for r in records if r["split"] == "train"]
val_records = [r for r in records if r["split"] == "validation"]
test_records = [r for r in records if r["split"] == "test"]

# Your exercise begins here:

# 1. Print the number of records in each partition.

# 2. Print the label distribution for each partition.

# 3. Confirm no group_id appears in more than one partition.

# 4. Print the text and numeric label of the first training record.
