from copy import deepcopy

import pytest

from src.content_reference import load_source
from src.global_annotation_schema import COUNTRY_CODES, evidence_targets, validate_article


def validate(c, article=None):
    ref, text, _ = load_source(c["root"], c["source"])
    return validate_article(article or c["annotation"], c["taxonomy"], c["policy"], text, ref["content_revision_sha256"])


def reground(c, article):
    ref, text, _ = load_source(c["root"], c["source"])
    article["evidence"] = [{"target": target, "content_revision_sha256": ref["content_revision_sha256"],
                            "start": 0, "end": len(text), "quote": text, "attribution": "Synthetic source"}
                           for target in sorted(evidence_targets(article))]
    return article


def test_worldwide_country_roles_and_no_topic(global_case):
    c = global_case
    assert len(COUNTRY_CODES) == 249
    assert validate(c)["countries"] == [{"code": "KE", "role": "host"}, {"code": "BR", "role": "participant"}]
    assert "TW" in COUNTRY_CODES and "CN" in COUNTRY_CODES
    assert "topic" not in c["annotation"]


@pytest.mark.parametrize("code", ["ZZ", "UK", "XK", "us", "USA", "", 123])
def test_country_membership_is_validated(global_case, code):
    c = global_case
    c["annotation"]["countries"][0]["code"] = code
    with pytest.raises(ValueError, match="country code"):
        validate(c)


@pytest.mark.parametrize("value", ["2026-1-2", "2026-02-30", "2026-11-20T00:00:00Z", "20-11-2026", 20261120])
def test_strict_date_validation(global_case, value):
    c = global_case
    c["annotation"]["event_date"] = value
    with pytest.raises(ValueError):
        validate(c)


@pytest.mark.parametrize("mutation", ["target", "hash", "offset", "quote", "bool_offset", "attribution", "missing_field"])
def test_forged_and_missing_evidence_rejected(global_case, mutation):
    c = global_case
    evidence = c["annotation"]["evidence"][0]
    if mutation == "target":
        evidence["target"] = "/rationale"
    elif mutation == "hash":
        evidence["content_revision_sha256"] = "0" * 64
    elif mutation == "offset":
        evidence["end"] += 1
    elif mutation == "quote":
        evidence["quote"] = "Invented source quote"
    elif mutation == "bool_offset":
        evidence["start"] = False
    elif mutation == "attribution":
        evidence["attribution"] = ""
    else:
        c["annotation"]["evidence"].pop()
    with pytest.raises(ValueError):
        validate(c)


def test_multidomain_multievent_article_preserves_instances(global_case):
    c = global_case
    article = c["annotation"]
    article["domains"] += ["geopolitics", "economics"]
    article["defense_event_types"].append("military_diplomacy")
    diplomacy = deepcopy(article["events"][0])
    diplomacy.update(instance_id="diplomacy-1", domains=["defense", "geopolitics"],
                     defense_event_types=["military_diplomacy"], event_date="2026-11-21")
    trade = deepcopy(diplomacy)
    trade.update(instance_id="trade-1", domains=["economics"], defense_event_types=[])
    article["events"] += [diplomacy, trade]
    article["event_date"] = None
    assert len(validate(c, reground(c, article))["events"]) == 3


def test_multi_event_dates_cannot_be_conflated(global_case):
    c = global_case
    second = deepcopy(c["annotation"]["events"][0])
    second.update(instance_id="later-exercise", event_date="2026-11-21")
    c["annotation"]["events"].append(second)
    with pytest.raises(ValueError, match="Multiple event values"):
        validate(c)


@pytest.mark.parametrize("mutation", ["duplicate_instance", "complete_missing_events", "not_enumerated_with_events",
                                    "partial_without_note", "event_outside_article", "event_country_outside_article"])
def test_event_scope_consistency(global_case, mutation):
    c = global_case
    article = c["annotation"]
    if mutation == "duplicate_instance":
        article["events"] *= 2
    elif mutation == "complete_missing_events":
        article["events"] = []
    elif mutation == "not_enumerated_with_events":
        article.update(event_coverage="not_enumerated", event_coverage_note="Not enumerated")
    elif mutation == "partial_without_note":
        article["event_coverage"] = "partial"
    elif mutation == "event_outside_article":
        article["events"][0]["domains"].append("economics")
    else:
        article["events"][0]["countries"].append({"code": "NG", "role": "actor"})
    with pytest.raises(ValueError):
        validate(c)


def test_article_only_annotation_is_explicit(global_case):
    c = global_case
    article = c["annotation"]
    article.update(events=[], event_coverage="not_enumerated", event_coverage_note="Only article-level tags reviewed")
    assert not validate(c, reground(c, article))["events"]


def test_nondefense_and_other_rules(global_case):
    c = global_case
    article = c["annotation"]
    article.update(domains=["economics"], defense_event_types=[], events=[], event_coverage="not_enumerated",
                   event_coverage_note="Article-level economic reporting")
    assert validate(c, reground(c, article))["domains"] == ["economics"]
    article["domains"] = ["other", "economics"]
    with pytest.raises(ValueError, match="other is exclusive"):
        validate(c)


@pytest.mark.parametrize("mutation", ["missing_defense_type", "unknown_type", "nondefense_type", "fallback_and_named", "independent_claim"])
def test_defense_category_and_evidence_status_rules(global_case, mutation):
    c = global_case
    article = c["annotation"]
    if mutation == "missing_defense_type":
        article["defense_event_types"] = []
    elif mutation == "unknown_type":
        article["defense_event_types"] = ["made_up_type"]
    elif mutation == "nondefense_type":
        article["domains"] = ["economics"]
    elif mutation == "fallback_and_named":
        article["defense_event_types"].append("defense_other")
        article["events"][0]["defense_event_types"].append("defense_other")
    else:
        article["evidence_status"] = "independently_corroborated"
    with pytest.raises(ValueError):
        validate(c)


def test_defense_fallback_does_not_force_a_named_category(global_case):
    c = global_case
    c["annotation"]["defense_event_types"] = ["defense_other"]
    c["annotation"]["events"][0]["defense_event_types"] = ["defense_other"]
    assert validate(c)["defense_event_types"] == ["defense_other"]
