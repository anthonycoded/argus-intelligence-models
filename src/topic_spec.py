"""Versioned, explicit topic specifications for AIC-1 annotation.

Keep topic policies separate from annotations so changes are reviewable.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED = (
    "topic_id", "policy_version", "title", "mandatory_subject",
    "geographic_scope", "material_connection", "exclusions",
    "labeling_guidance",
)
LABELS = ("relevant", "partially_relevant", "unrelated")


def validate_topic_spec(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("topic specification must be a JSON object")
    missing = sorted(set(REQUIRED) - set(value))
    extra = sorted(set(value) - set(REQUIRED))
    if missing or extra:
        raise ValueError(f"topic specification keys: missing={missing}, extra={extra}")
    for key in REQUIRED:
        if key in ("exclusions", "labeling_guidance"):
            continue
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError(f"{key} must be a nonempty string")
    if not isinstance(value["exclusions"], list) or not value["exclusions"]:
        raise ValueError("exclusions must be a nonempty list")
    if any(not isinstance(s, str) or not s.strip() for s in value["exclusions"]):
        raise ValueError("each exclusion must be a nonempty string")
    guidance = value["labeling_guidance"]
    if not isinstance(guidance, dict) or set(guidance) != set(LABELS):
        raise ValueError(f"labeling_guidance must define exactly {LABELS}")
    if any(not isinstance(guidance[label], str) or not guidance[label].strip() for label in LABELS):
        raise ValueError("each labeling_guidance entry must be a nonempty string")
    return value


def read_topic_spec(path: str | Path) -> dict:
    file = Path(path)
    try:
        value = json.loads(file.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid topic specification JSON: {exc}") from exc
    return validate_topic_spec(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a versioned AIC-1 topic specification")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    topic = read_topic_spec(args.path)
    print(f"Topic validated: {topic['topic_id']} ({topic['policy_version']})")


if __name__ == "__main__":
    main()
