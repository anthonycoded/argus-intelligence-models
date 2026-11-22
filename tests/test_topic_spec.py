import copy
import json
from pathlib import Path

import pytest

from src.topic_spec import read_topic_spec, validate_topic_spec

TOPIC_FILE = Path(__file__).resolve().parents[1] / "topics" / "taiwan_military_v1.json"


def test_example_topic_is_valid():
    assert read_topic_spec(TOPIC_FILE)["topic_id"] == "taiwan-military"


def test_reject_missing_mandatory_subject():
    data = read_topic_spec(TOPIC_FILE).copy()
    del data["mandatory_subject"]
    with pytest.raises(ValueError, match="mandatory_subject"):
        validate_topic_spec(data)


def test_reject_empty_exclusions():
    data = read_topic_spec(TOPIC_FILE).copy()
    data["exclusions"] = []
    with pytest.raises(ValueError, match="exclusions"):
        validate_topic_spec(data)


def test_reject_missing_label_rule():
    data = copy.deepcopy(read_topic_spec(TOPIC_FILE))
    del data["labeling_guidance"]["partially_relevant"]
    with pytest.raises(ValueError, match="labeling_guidance"):
        validate_topic_spec(data)


def test_reject_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{bad-json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid topic specification"):
        read_topic_spec(path)
