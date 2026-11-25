# AIC-1 Synthetic Dataset v2 — educational binary defense classifier

This is a **new synthetic replacement fixture**, **not** a modification of your existing AIC-1 repository or its protected rights-controlled data.

## Contents

- `aic1_synthetic_v2.jsonl`: 160 JSON Lines records, 80 labeled `defense` and 80 `nondefense`.
- `group_splits.jsonl`: 80 independent fictional scenario groups, each assigned to train, validation, or test.
- `manifest.json`: distribution and provenance summary.
- `build.py`: deterministic creation script for the fictional scenarios and split manifest.

## Why it's better than v1

- 80 different fictional situations instead of two underlying phrases.
- 33 hard-negative **scenarios** (66 records), e.g. civilian drones, old munitions, municipal cyberattacks, coastal sensors, transport security, commercial vessels and dual-use technology.
- 9 harder defense-positive scenarios (18 records), e.g. military medical policy, cybersecurity at military bases, armed forces safety incidents and logistics.
- Defense subtypes include combat, deployment, exercises, procurement, intelligence/surveillance, policy, technology, military diplomacy, and defense-other.
- 2 text versions per scenario; both versions always stay in the **same split** to prevent same-story overlap.
- Split: 112 train / 24 validation / 24 test, equal class distribution in each partition.
- No `SYNTHETIC FIXTURE N` marker or class label embedded in model input text.

## Existing schema compatibility

The main JSONL retains the original keys `fixture_id`, `fixture_target`, `group_id`, `label_origin`, `synthetic`, `text`. The IDs and label origin explicitly mark this data as synthetic and **not** human-approved. Do **not** import it into the production annotation-approval ledger or treat it as rights-cleared article content.

Read training text only from `text`; labels only from `fixture_target`. Use `group_id` to assign train/validation/test using `group_splits.jsonl`. Do not feed metadata fields as model inputs.

## What it cannot prove

All records are AI-authored fictional educational fixtures. They're intentionally short, unlike production articles, and some contain explanatory descriptions (e.g. 'not a military operation'). There are recurring editorial formulas and repeated descriptions in two variants per story, which can produce shortcuts even with grouped splitting. This dataset is for developing, debugging and learning the training/evaluation workflow. **High test metrics on v2 do not demonstrate real-world generalization, model readiness, production rights clearance or actual human annotation quality.**

For realistic evaluation, later use diverse, independently sourced, appropriately authorized real documents with human-verified labels and a held-out split by event/source group.

## Beginner-friendly exercise

```python
import json
from pathlib import Path
from collections import Counter
root = Path('aic1_synthetic_v2')
records = [json.loads(line) for line in (root/'aic1_synthetic_v2.jsonl').open(encoding='utf-8')]
splits = {row['group_id']: row['split'] for row in map(json.loads, (root/'group_splits.jsonl').open(encoding='utf-8'))}
for split in ('train','validation','test'):
    subset = [r for r in records if splits[r['group_id']] == split]
    print(split, len(subset), Counter(r['fixture_target'] for r in subset))
```

Expected: train 112 (56 / 56), validation 24 (12 / 12), test 24 (12 / 12).
