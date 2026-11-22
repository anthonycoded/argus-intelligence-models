import json
from collections import Counter
from datetime import datetime
from pathlib import Path

LABELS = ("unrelated", "partially_relevant", "relevant")
REQUIRED = (
    "record_id", "event_group_id", "source_id", "collected_at",
    "topic", "subject_spec", "article_title", "article_text", "label",
    "label_source", "rationale", "annotation_version",
)


def validate_record(record: dict, line: int) -> None:
    if not isinstance(record, dict):
        raise ValueError(f"Line {line}: expected JSON object")
    missing = [key for key in REQUIRED if key not in record]
    if missing:
        raise ValueError(f"Line {line}: missing {missing}")
    for key in REQUIRED:
        if not isinstance(record[key], str) or not record[key].strip():
            raise ValueError(f"Line {line}: {key} must be a non-empty string")
    if record["label"] not in LABELS:
        raise ValueError(f"Line {line}: invalid label")
    if record["label_source"] != "human_verified":
        raise ValueError(f"Line {line}: training labels must be human_verified")
    try:
        dt = datetime.fromisoformat(record["collected_at"].replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError as exc:
        raise ValueError(f"Line {line}: invalid collected_at: {exc}") from exc
    from .annotation_schema import validate_annotation
    validate_annotation(record, line)


def read_records(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(path)
    records = []
    seen = set()
    for num, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Line {num}: invalid JSON: {exc}") from exc
        validate_record(rec, num)
        if rec["record_id"] in seen:
            raise ValueError(f"Line {num}: duplicate record_id {rec['record_id']}")
        seen.add(rec["record_id"])
        records.append(rec)
    return records


def counts(records: list[dict]) -> dict[str, int]:
    tally = Counter(row["label"] for row in records)
    return {label: tally[label] for label in LABELS}
