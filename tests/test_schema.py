import pytest
from src.schema import read_records, validate_record
from src.split_dataset import split_grouped


def record(**overrides):
    r = dict(record_id="r1", event_group_id="e1", source_id="s1",
             collected_at="2026-11-21T20:00:00Z", topic="Taiwan Strait",
             subject_spec="Mandatory subject: PLA activity near Taiwan", article_title="Example",
             article_text="Test article content for schema validation",
             label="relevant", label_source="human_verified", rationale="Matches subject",
             annotation_version="v1")
    r.update(overrides)
    return r


def test_valid():
    validate_record(record(), 1)


def test_reject_llm_pseudolabel():
    with pytest.raises(ValueError, match="human_verified"):
        validate_record(record(label_source="llm"), 1)


def test_reject_invalid_label():
    with pytest.raises(ValueError, match="invalid label"):
        validate_record(record(label="maybe"), 1)


def test_reject_timezone_naive():
    with pytest.raises(ValueError, match="invalid collected_at"):
        validate_record(record(collected_at="2026-11-21T20:00:00"), 1)


def test_empty_dataset(tmp_path):
    file = tmp_path / "empty.jsonl"
    file.write_text("", encoding="utf8")
    assert read_records(file) == []


def test_group_disjoint():
    rows = []
    for label in ("unrelated", "partially_relevant", "relevant"):
        for i in range(12):
            rows.append(record(record_id=f"{label}-{i}",event_group_id=f"{label}-event-{i}",label=label))
    parts = split_grouped(rows)
    sets = {name: {r["event_group_id"] for r in part} for name, part in parts.items()}
    assert not (sets["train"] & sets["validation"])
    assert not (sets["train"] & sets["test"])
    assert not (sets["validation"] & sets["test"])
