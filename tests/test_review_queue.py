import json
import pytest

from src.review_queue import add_article, approve_article

TOPIC = "topics/taiwan_military_v1.json"


def article():
    return {
        "event_group_id": "event-001",
        "source_id": "local-article-001",
        "collected_at": "2026-11-21T20:00:00Z",
        "article_title": "Illustrative report",
        "article_text": "Fictional example text, not a real training article.",
    }


def review(label="relevant"):
    return {
        "label": label,
        "rationale": "A human verified all four assessment criteria using the full article.",
        "criteria": {
            "mandatory_subject": {"assessment": "met", "evidence": "Fictional military exercises cited"},
            "geography": {"assessment": "met", "evidence": "Fictional Taiwan Strait location cited"},
            "material_connection": {"assessment": "met", "evidence": "Fictional military deployment cited"},
            "exclusion": {"assessment": "not_met", "evidence": "No applicable exclusion in fictional example"},
        }
    }


def setup(tmp_path):
    inp = tmp_path / "article.json"
    inp.write_text(json.dumps(article()), encoding="utf-8")
    queue = tmp_path / "queue"
    approved = tmp_path / "approved.jsonl"
    key = add_article(inp, TOPIC, queue, approved)
    return inp, queue, approved, key


def test_add_creates_pending_only(tmp_path):
    _, queue, approved, key = setup(tmp_path)
    assert (queue / f"{key}.json").exists()
    assert not approved.exists()


def test_duplicate_intake_rejected(tmp_path):
    inp, queue, approved, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="Duplicate"):
        add_article(inp, TOPIC, queue, approved)


def test_human_confirmation_required(tmp_path):
    _, queue, approved, key = setup(tmp_path)
    path = tmp_path / "review.json"
    path.write_text(json.dumps(review()), encoding="utf-8")
    with pytest.raises(ValueError, match="confirm-human-review"):
        approve_article(key, path, queue, approved)
    assert not approved.exists()


def test_approve_validates_and_exports(tmp_path):
    _, queue, approved, key = setup(tmp_path)
    path = tmp_path / "review.json"
    path.write_text(json.dumps(review()), encoding="utf-8")
    row = approve_article(key, path, queue, approved, True)
    assert row["label_source"] == "human_verified"
    assert len(approved.read_text(encoding="utf-8").splitlines()) == 1
    assert not (queue / f"{key}.json").exists()


def test_conflicting_label_rejected_without_losing_pending(tmp_path):
    _, queue, approved, key = setup(tmp_path)
    r = review()
    r["criteria"]["mandatory_subject"]["assessment"] = "not_met"
    path = tmp_path / "review.json"
    path.write_text(json.dumps(r), encoding="utf-8")
    with pytest.raises(ValueError, match="mandatory_subject"):
        approve_article(key, path, queue, approved, True)
    assert (queue / f"{key}.json").exists()
    assert not approved.exists()


def test_invalid_article_rejected(tmp_path):
    inp = tmp_path / "bad.json"
    a = article()
    a["collected_at"] = "2026-11-21T20:00:00"
    inp.write_text(json.dumps(a), encoding="utf-8")
    with pytest.raises(ValueError, match="timezone"):
        add_article(inp, TOPIC, tmp_path / "queue", tmp_path / "approved.jsonl")
