from copy import deepcopy
import json

import pytest

from src.global_discovery import rank_global
from src.global_io import digest, encoded, read_object
from src.global_review import approve, attest_rights, create_draft
from src.global_sampling import load_sample, prepare_review, sample_ranking, select_candidates
from src.ranking_benchmark import benchmark


def config(**updates):
    return {"schema_version": "aic-global-sampling-v1", "seed": 42, "per_stratum": 2, "publisher_cap": 100, "region_cap": 1000, "max_total": 1000, **updates}


def rows(n=30):
    return [{"candidate_id": f"candidate-{i:064x}", "source_id": f"https://example.org/{i}",
             "publisher": "Dominant" if i < 20 else "Other", "source_region": "North America" if i < 20 else "Africa",
             "language": "en", "ranking": {"query_hint": "defense" if i % 2 else "economics",
                "semantic_score": .8 if i % 3 == 0 else .4 if i % 3 == 1 else .1, "keyword_score": 0}}
            for i in range(n)]


def test_sampling_seed_reproducibility_and_order_invariance():
    selected, design = select_candidates(rows(), config())
    assert (selected, design) == select_candidates(list(reversed(rows())), config())
    assert selected != select_candidates(rows(), config(seed=9))[0]


def test_publisher_caps_and_low_score_exploration():
    selected, design = select_candidates(rows(), config(publisher_cap=3))
    assert sum(r["publisher"] == "Dominant" for r in selected) <= 3
    assert any(r["publisher"] == "Other" for r in selected)
    assert design["caps_or_budget_applied"]
    assert all(r["sampling"]["inclusion_probability"] is None for r in selected)


def test_region_caps_apply_across_many_publishers():
    population = rows(30)
    for i, row in enumerate(population):
        row["publisher"] = f"Independent publisher {i}"
    selected, design = select_candidates(population, config(region_cap=3))
    assert sum(r["source_region"] == "North America" for r in selected) <= 3
    assert sum(r["source_region"] == "Africa" for r in selected) <= 3
    assert design["caps_or_budget_applied"]


def test_uncapped_inclusion_probabilities_and_disagreement_candidates():
    selected, design = select_candidates(rows(), config())
    assert not design["caps_or_budget_applied"]
    assert all(0 < r["sampling"]["inclusion_probability"] <= 1 for r in selected)
    assert any("randomized_low_score_exploration" in r["sampling"]["selection_reasons"] for r in selected)
    assert any("semantic_keyword_disagreement_hard_negative_candidate_not_label" in r["sampling"]["selection_reasons"] for r in selected)


@pytest.fixture
def ranked_case(global_case, tmp_path):
    c = global_case
    source = tmp_path / "raw.jsonl"
    source.write_bytes(encoded({"source_id": c["metadata"]["source_id"], "article_title": c["metadata"]["article_title"],
                               "publisher": c["metadata"]["publisher"], "source_region": "Africa", "language": "en",
                               "collected_at": c["metadata"]["collected_at"]}) + b"\n")
    rank_global([source], tmp_path / "ranking", tmp_path / "cache", revision="a" * 40,
                encoder=lambda texts: [[1., 0.] for _ in texts], encoder_id="synthetic-only")
    sample_ranking(tmp_path / "ranking", tmp_path / "sample", config())
    return c, tmp_path / "ranking", tmp_path / "sample"


def test_sample_diagnostics_and_integrity(ranked_case):
    _, _, sample = ranked_case
    manifest, selected = load_sample(sample)
    assert len(selected) == 1
    assert manifest["selected"]["representativeness"] == "not_established"
    assert manifest["selected"]["missing_regions"]
    path = sample / "sample.jsonl"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="integrity"):
        load_sample(sample)


def test_sample_profile_binding_cannot_be_replaced(ranked_case):
    _, _, sample = ranked_case
    path = sample / "manifest.json"
    obj = read_object(path)
    obj["profile_sha256"] = "0" * 64
    path.write_bytes(encoded(obj))
    with pytest.raises(ValueError, match="profile"):
        load_sample(sample)


def test_intake_only_registers_content_and_never_supplies_labels(ranked_case, tmp_path):
    c, _, sample = ranked_case
    ident = load_sample(sample)[1][0]["candidate_id"]
    store = tmp_path / "intake-store"
    result = prepare_review(sample, ident, store, c["text_file"], "human_summary", "Synthetic content only")
    assert not (store / "approvals").exists() and not (store / "rights").exists()
    receipt = read_object(store / "intake" / result["receipt_id"] / "receipt.json")
    assert receipt["state"] == "awaiting_human_global_draft" and receipt["inferred_annotations"] is None


def test_unreviewed_articles_are_never_negatives(ranked_case):
    c, ranking, _ = ranked_case
    result = benchmark(ranking, c["root"], k=1)
    assert result["human_reviewed"] == 0 and result["unreviewed_not_negative"] == 1
    assert all(v["precision_at_k"] is None and v["recall_at_k"] is None for v in result["metrics"].values())


def test_fully_human_reviewed_denominators_are_defined(ranked_case):
    c, ranking, _ = ranked_case
    d = create_draft(c["root"], c["source"], c["annotation"])
    approve(c["root"], d, "human-reviewer", True)
    result = benchmark(ranking, c["root"], k=1)
    assert result["recall_denominator_defined"]
    assert all(v["precision_at_k"] == v["recall_at_k"] == 1 for v in result["metrics"].values())
    insufficient_k = benchmark(ranking, c["root"], k=5)
    assert insufficient_k["metrics"]["semantic"]["precision_at_k"] is None


def test_sampling_cohort_integration_requires_separate_human_approval_and_rights(ranked_case, tmp_path):
    from src.global_dataset import export_dataset, validate_dataset
    c, _, sample = ranked_case
    selected = load_sample(sample)[1][0]
    store = tmp_path / "prepared-store"
    result = prepare_review(sample, selected["candidate_id"], store, c["text_file"], "human_summary", "Synthetic content")
    source_id = result["source_ref_id"]
    draft_id = create_draft(store, source_id, c["annotation"])
    approval_id = approve(store, draft_id, "global-human-reviewer", True)
    cohort = {"schema_version": "aic-global-cohort-v1", "reviewed_by": "group-reviewer", "reviewed_at": "2026-11-22T00:00:00Z", "confirm_group_review": True,
              "items": [{"source_ref_id": source_id, "approval_id": approval_id, "event_group_ids": ["human-exercise-group"], "duplicate_group_ids": [],
                         "regions": ["Africa", "South America"], "language": "en", "sampling": {"path": "sample", "manifest_sha256": digest((sample / "manifest.json").read_bytes()), "candidate_id": selected["candidate_id"]}}]}
    path = tmp_path / "cohort.json"
    path.write_bytes(encoded(cohort))
    with pytest.raises(ValueError, match="rights"):
        export_dataset(store, path, tmp_path / "blocked")
    attest_rights(store, source_id, "cleared", "Explicit synthetic test material rights", "rights-reviewer", True)
    export_dataset(store, path, tmp_path / "snapshot")
    manifest = validate_dataset(tmp_path / "snapshot")
    assert manifest["readiness"]["snapshot_eligible"]
    assert manifest["coverage"]["sampled_score_ranges"] == {"high": 1}
    assert not manifest["readiness"]["supervised_split_ready"]
    assert not manifest["readiness"]["training_supported"]
