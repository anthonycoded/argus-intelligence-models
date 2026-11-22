import pytest
from src.schema import validate_record


def annotated_record(**changes):
    result = {
        "record_id": "phase2-1", "event_group_id": "event-1", "source_id": "source-1",
        "collected_at": "2026-11-21T20:00:00Z", "topic": "Chinese military activity near Taiwan",
        "subject_spec": "Mandatory subject: PLA operations; Geography: Taiwan Strait; Exclusions: civilian-only news; Material connection: military movements",
        "article_title": "Synthetic test case", "article_text": "Synthetic PLA naval exercise near Taiwan (test only)",
        "label": "relevant", "label_source": "human_verified", "rationale": "Synthetic fixture for schema testing",
        "annotation_version": "v1.1", "annotation_policy_version": "aic1-policy-v1",
        "criteria": {
            "mandatory_subject": {"assessment": "met", "evidence": "PLA exercise described"},
            "geography": {"assessment": "met", "evidence": "Near Taiwan"},
            "material_connection": {"assessment": "met", "evidence": "Military exercise is direct"},
            "exclusion": {"assessment": "not_met", "evidence": "Not civilian-only"},
        },
    }
    result.update(changes)
    return result


def test_valid_structured_record():
    validate_record(annotated_record(), 1)


def test_reject_incomplete_criteria():
    row = annotated_record()
    del row["criteria"]["geography"]
    with pytest.raises(ValueError, match="exactly"):
        validate_record(row, 1)


def test_reject_relevant_without_mandatory_subject():
    row = annotated_record()
    row["criteria"]["mandatory_subject"]["assessment"] = "not_met"
    with pytest.raises(ValueError, match="mandatory_subject"):
        validate_record(row, 1)


def test_reject_exclusion_conflict():
    row = annotated_record()
    row["criteria"]["exclusion"]["assessment"] = "met"
    with pytest.raises(ValueError, match="exclusion"):
        validate_record(row, 1)


def test_reject_missing_evidence():
    row = annotated_record()
    row["criteria"]["geography"]["evidence"] = ""
    with pytest.raises(ValueError, match="evidence"):
        validate_record(row, 1)


def test_allow_old_flat_phase1_record():
    row = annotated_record()
    del row["criteria"]
    del row["annotation_policy_version"]
    validate_record(row, 1)
