"""Structured subject assessments for AIC-1, compatible with Phase 1 records."""
from __future__ import annotations

from typing import Any

ASSESSMENTS = ("met", "not_met", "uncertain", "not_applicable")
REQUIRED_CRITERIA = ("mandatory_subject", "geography", "material_connection", "exclusion")


def validate_annotation(record: dict[str, Any], line: int = 1) -> None:
    """Validate additional structured annotations when present.

    Records using the Phase 1 flat schema remain valid until migrated.
    A record opting into the Phase 2 schema must supply all assessments.
    """
    if "criteria" not in record:
        return

    criteria = record["criteria"]
    if not isinstance(criteria, dict):
        raise ValueError(f"Line {line}: criteria must be an object")
    if set(criteria) != set(REQUIRED_CRITERIA):
        raise ValueError(f"Line {line}: criteria must contain exactly {REQUIRED_CRITERIA}")

    for key, item in criteria.items():
        if not isinstance(item, dict):
            raise ValueError(f"Line {line}: criteria.{key} must be an object")
        if set(item) != {"assessment", "evidence"}:
            raise ValueError(f"Line {line}: criteria.{key} requires assessment and evidence")
        if item["assessment"] not in ASSESSMENTS:
            raise ValueError(f"Line {line}: invalid assessment for {key}")
        if not isinstance(item["evidence"], str) or not item["evidence"].strip():
            raise ValueError(f"Line {line}: evidence for {key} must be non-empty")

    if "annotation_policy_version" not in record or not isinstance(record["annotation_policy_version"], str) or not record["annotation_policy_version"].strip():
        raise ValueError(f"Line {line}: annotation_policy_version required")

    # Fail closed on obvious conflicts but do not infer every partial-relevance case.
    if record["label"] == "relevant":
        if criteria["mandatory_subject"]["assessment"] != "met":
            raise ValueError(f"Line {line}: relevant label requires mandatory_subject met")
        if criteria["geography"]["assessment"] not in ("met", "not_applicable"):
            raise ValueError(f"Line {line}: relevant label requires geography met/not_applicable")
        if criteria["material_connection"]["assessment"] != "met":
            raise ValueError(f"Line {line}: relevant label requires material_connection met")
        if criteria["exclusion"]["assessment"] != "not_met":
            raise ValueError(f"Line {line}: relevant label requires exclusion not_met")
