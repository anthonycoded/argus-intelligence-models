import json
from pathlib import Path

import pytest

from src.topic_spec import read_topic_spec
from src.retarget_pending import retarget_pending

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "topics" / "taiwan_military_v2.json"
V1 = ROOT / "topics" / "taiwan_military_v1.json"
CASES = ROOT / "examples" / "taiwan_policy_v2_regression_cases.json"


def test_v2_spec_validates_and_is_distinct_from_v1():
    assert read_topic_spec(V1)["policy_version"] == "aic1-taiwan-v1"
    assert read_topic_spec(V2)["policy_version"] == "aic1-taiwan-v2"


def test_case_matrix_covers_expected_policy_scenarios():
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    assert [c["case_id"] for c in cases] == [f"article-{i:03}" for i in range(1, 5)]
    assert [c["expected_label"] for c in cases] == [
        "relevant", "unrelated", "relevant", "partially_relevant"
    ]
    assert all(c["reason"] and c["description"] for c in cases)


def pending(tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    rid = "aic1-" + "a" * 32
    topic = read_topic_spec(V1)
    row = {
        "record_id": rid, "review_status": "pending", "topic_id": topic["topic_id"],
        "topic": topic["title"], "topic_policy_version": topic["policy_version"],
        "subject_spec": "original v1 specification", "article_text": "Preserve original",
    }
    path = queue / f"{rid}.json"
    path.write_text(json.dumps(row), encoding="utf-8")
    return rid, queue, path


def test_retarget_requires_explicit_confirmation(tmp_path):
    rid, queue, path = pending(tmp_path)
    with pytest.raises(ValueError, match="confirm-policy-change"):
        retarget_pending(rid, V2, queue)
    assert json.loads(path.read_text())["topic_policy_version"] == "aic1-taiwan-v1"


def test_retarget_preserves_identity_article_and_pending_status(tmp_path):
    rid, queue, path = pending(tmp_path)
    row = retarget_pending(rid, V2, queue, confirm=True)
    assert row["record_id"] == rid
    assert row["article_text"] == "Preserve original"
    assert row["review_status"] == "pending"
    assert row["topic_policy_version"] == "aic1-taiwan-v2"
    assert row["policy_change_history"] == [{"from": "aic1-taiwan-v1", "to": "aic1-taiwan-v2"}]
    assert json.loads(path.read_text())["topic_policy_version"] == "aic1-taiwan-v2"


def test_retarget_rejects_nonpending_or_wrong_topic(tmp_path):
    rid, queue, path = pending(tmp_path)
    row = json.loads(path.read_text())
    row["review_status"] = "approved"
    path.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="pending"):
        retarget_pending(rid, V2, queue, confirm=True)
    row["review_status"] = "pending"
    row["topic_id"] = "unrelated-topic"
    path.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="mismatch"):
        retarget_pending(rid, V2, queue, confirm=True)


def test_retarget_rejects_repeat_without_changes(tmp_path):
    rid, queue, _ = pending(tmp_path)
    retarget_pending(rid, V2, queue, confirm=True)
    with pytest.raises(ValueError, match="already uses"):
        retarget_pending(rid, V2, queue, confirm=True)
