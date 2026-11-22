# AIC-1 Phase 2B — Topic Specification

Additive patch; copy `src/`, `tests/`, and `topics/` into the existing project root. No existing files are overwritten.

Run:

```bat
python -m pytest -q
python -m src.topic_spec topics/taiwan_military_v1.json
python -m src.validate_dataset data/labeled/pilot.jsonl
```

The specification is a **draft annotation policy**, not a verified intelligence claim. Review and freeze it before human labeling; do not silently alter a policy version after labels have been created under it. If policy changes, issue a new version and audit or re-label affected examples.

Keep records under the existing flat Phase 1/2 schema. Use the topic's `title` as `topic`, its full criteria as a clearly worded `subject_spec`, and set `annotation_policy_version` to `aic1-taiwan-v1` when creating *human-verified* structured annotations. The topic document alone does not generate verified records.

The next step is collecting source-backed article/topic pairs and creating a human review queue. Do not promote drafts or synthetic fixtures to `data/labeled/pilot.jsonl`.
