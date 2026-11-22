# AIC-1 Phase 2 annotation schema patch

Copy `src/` and `tests/` into the existing Phase 1 project, preserving all other files.
Copy `examples/annotation_template_v2.json` to `examples/`.

Run from your active virtual environment:

    python -m pytest -q
    python -m src.validate_dataset data/labeled/pilot.jsonl

Expected: 12 tests passing if using the original six-test starter; pilot has zero records until annotated.

The template is NOT a real article and MUST NOT be added to training data.

Compatibility: existing Phase 1 records remain valid. Records that include `criteria` must include all four structured assessments and an annotation policy version.

Assessment semantics: `met` means the criterion is satisfied, `not_met` means it is not, `uncertain` needs human review, `not_applicable` means the specification does not require it. For `exclusion`, `met` means an exclusion IS triggered, so a `relevant` label requires `not_met`.

This validator only enforces clear contradictions for the `relevant` label. Complex partial/unrelated decisions require the human labeling policy and review process. Future work: topic-spec schema, independent adjudication, provenance checks, deduplication, and sampled audits.
