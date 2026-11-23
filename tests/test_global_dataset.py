from copy import deepcopy
import shutil

import pytest

from src.content_reference import register_source
from src.global_annotation_schema import evidence_targets
from src.global_dataset import (build_rows, components, export_dataset, split_rows, stress_partitions,
                                validate_dataset, validate_partitions)
from src.global_io import digest, document_hash, encoded, read_object
from src.global_review import approve, attest_rights, create_draft, revise


@pytest.fixture(scope="module")
def frozen_store_base(tmp_path_factory):
    base = tmp_path_factory.mktemp("phase2n-synthetic-base")
    store = base / "store"
    text = base / "text.txt"
    items = []
    for i in range(36):
        positive = i % 2 == 0
        body = f"Synthetic report {i}: military exercise." if positive else f"Synthetic report {i}: economic policy."
        text.write_bytes(body.encode())
        metadata = {"source_id": f"https://publisher{i % 3}.example.org/story/{i}", "publisher": f"Synthetic Publisher {i % 3}",
                    "adapter": "manual", "article_title": f"Independent synthetic article {i}", "published_at": f"2026-11-{i % 28 + 1:02}T12:00:00Z",
                    "published_at_raw": None, "collected_at": "2026-11-22T00:00:00Z", "content_type": "human_summary",
                    "rights_note": "Synthetic test content only", "provenance_method": "synthetic_test"}
        source = register_source(store, metadata, text)
        article = {"schema_version": "aic-global-annotation-v2", "domains": ["defense" if positive else "economics"],
                   "defense_event_types": ["military_exercise"] if positive else [], "countries": [], "organizations": [],
                   "event_date": None, "event_location": None, "evidence_status": "reported", "rationale": "Synthetic human review",
                   "events": [], "event_coverage": "not_enumerated", "event_coverage_note": "Article-level synthetic annotation", "evidence": []}
        article["evidence"] = [{"target": target, "content_revision_sha256": digest(body.encode()), "start": 0, "end": len(body),
                                "quote": body, "attribution": "Synthetic source"} for target in sorted(evidence_targets(article))]
        draft = create_draft(store, source, article)
        approval = approve(store, draft, "synthetic-human-reviewer", True)
        attest_rights(store, source, "cleared", "Synthetic test rights only", "synthetic-rights-reviewer", True)
        items.append({"source_ref_id": source, "approval_id": approval, "event_group_ids": [f"human-reviewed-event-{i}"],
                      "duplicate_group_ids": [], "regions": [["Africa", "Europe", "South America"][i % 3]], "language": "en", "sampling": None})
    cohort = {"schema_version": "aic-global-cohort-v1", "reviewed_by": "group-reviewer", "reviewed_at": "2026-11-22T00:00:00Z",
              "confirm_group_review": True, "items": items}
    (base / "cohort.json").write_bytes(encoded(cohort))
    return base


@pytest.fixture
def dataset_case(tmp_path, frozen_store_base):
    shutil.copytree(frozen_store_base, tmp_path / "case")
    root = tmp_path / "case"
    return root, root / "store", root / "cohort.json"


def test_global_export_and_manifest_validation(dataset_case):
    root, store, cohort = dataset_case
    manifest = export_dataset(store, cohort, root / "dataset", seed=7)
    assert manifest == validate_dataset(root / "dataset")
    assert manifest["readiness"]["supervised_split_ready"]
    assert manifest["coverage"]["human_annotated"] and manifest["coverage"]["missing_regions"]
    assert not manifest["readiness"]["training_supported"]
    assert (root / "dataset/test.jsonl").exists()


def test_dataset_bytes_are_reproducible_and_never_overwritten(dataset_case):
    root, store, cohort = dataset_case
    a = export_dataset(store, cohort, root / "a", seed=23)
    b = export_dataset(store, cohort, root / "b", seed=23)
    assert a == b
    for name in a["files"]:
        assert (root / "a" / name).read_bytes() == (root / "b" / name).read_bytes()
    with pytest.raises(FileExistsError):
        export_dataset(store, cohort, root / "a")


@pytest.mark.parametrize("target", ["snapshot.jsonl", "train.jsonl", "validation.jsonl", "test.jsonl", "cohort.json"])
def test_dataset_file_tampering_rejected(dataset_case, target):
    root, store, cohort = dataset_case
    export_dataset(store, cohort, root / "dataset")
    path = root / "dataset" / target
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="contents mismatch"):
        validate_dataset(root / "dataset")


def test_rehashing_tampered_split_does_not_bypass_source_approval(dataset_case):
    root, store, cohort = dataset_case
    export_dataset(store, cohort, root / "dataset")
    path = root / "dataset/train.jsonl"
    path.write_bytes(path.read_bytes().replace(b'"task_label":"defense"', b'"task_label":"nondefense"', 1))
    manifest = read_object(root / "dataset/manifest.json")
    manifest["files"]["train.jsonl"] = digest(path.read_bytes())
    manifest["manifest_id"] = document_hash({k: v for k, v in manifest.items() if k != "manifest_id"})
    (root / "dataset/manifest.json").write_bytes(encoded(manifest))
    with pytest.raises(ValueError, match="evidence mismatch"):
        validate_dataset(root / "dataset")


@pytest.mark.parametrize("mutation", ["unreviewed_grouping", "missing_approval", "missing_event_groups", "duplicate_source"])
def test_unsupported_cohort_fails_before_publication(dataset_case, mutation):
    root, store, path = dataset_case
    cohort = read_object(path)
    if mutation == "unreviewed_grouping":
        cohort["confirm_group_review"] = False
    elif mutation == "missing_approval":
        cohort["items"][0]["approval_id"] = "approval-" + "0" * 64
    elif mutation == "missing_event_groups":
        cohort["items"][0]["event_group_ids"] = []
    else:
        cohort["items"].append(deepcopy(cohort["items"][0]))
    path.write_bytes(encoded(cohort))
    with pytest.raises(ValueError):
        export_dataset(store, path, root / "blocked")
    assert not (root / "blocked").exists()


@pytest.mark.parametrize("mutation", ["missing_rights", "restricted_rights", "conflicting_rights", "stale_content", "stale_approval", "stale_cohort"])
def test_live_evidence_changes_invalidate_frozen_dataset(dataset_case, mutation):
    root, store, cohort = dataset_case
    export_dataset(store, cohort, root / "dataset")
    item = read_object(cohort)["items"][0]
    rights_dir = store / "rights" / item["source_ref_id"]
    if mutation == "missing_rights":
        shutil.rmtree(rights_dir)
    elif mutation in {"restricted_rights", "conflicting_rights"}:
        if mutation == "restricted_rights":
            shutil.rmtree(rights_dir)
        attest_rights(store, item["source_ref_id"], "restricted", "Synthetic restriction", "reviewer", True)
    elif mutation == "stale_content":
        (store / "sources" / item["source_ref_id"] / "content.utf8").write_bytes(b"changed")
    elif mutation == "stale_approval":
        approval = read_object(store / "approvals" / item["approval_id"] / "approval.json")
        revised = revise(store, item["approval_id"], approval["annotation"])
        approve(store, revised, "new-reviewer", True)
    else:
        cohort.write_bytes(cohort.read_bytes() + b" ")
    with pytest.raises(ValueError):
        validate_dataset(root / "dataset")


@pytest.mark.parametrize("identity", ["canonical_source_id", "content_revision_sha256", "duplicate_fingerprint", "event_group_ids", "duplicate_group_ids"])
def test_transitive_group_identities_never_cross_splits(dataset_case, identity):
    _, store, path = dataset_case
    rows, _ = build_rows(store, read_object(path), path.parent)
    rows[0][identity] = rows[1][identity] = ["shared-group"] if identity.endswith("ids") else "shared-identity"
    parts = split_rows(rows, 7)
    owners = {r["source_ref_id"]: name for name, part in parts.items() for r in part}
    assert owners[rows[0]["source_ref_id"]] == owners[rows[1]["source_ref_id"]]
    validate_partitions(parts)


def test_explicit_leakage_is_rejected(dataset_case):
    _, store, path = dataset_case
    rows, _ = build_rows(store, read_object(path), path.parent)
    parts = split_rows(rows, 42)
    parts["test"][0]["event_group_ids"] = parts["train"][0]["event_group_ids"]
    with pytest.raises(ValueError, match="leakage"):
        validate_partitions(parts)


def test_optional_publisher_and_time_protocols_are_separate(dataset_case):
    root, store, path = dataset_case
    manifest = export_dataset(store, path, root / "stress", publisher_holdout=["Synthetic Publisher 0"], time_cutoff="2026-11-15T00:00:00Z")
    assert "publisher" in manifest["stress_diagnostics"] and "time" in manifest["stress_diagnostics"]
    assert (root / "stress/stress-publisher-holdout.jsonl").exists()
    assert validate_dataset(root / "stress") == manifest


def test_mixed_event_components_and_unknown_dates_are_quarantined(dataset_case):
    _, store, path = dataset_case
    rows, _ = build_rows(store, read_object(path), path.parent)
    rows[0]["event_group_ids"] = rows[1]["event_group_ids"] = ["cross-publisher-event"]
    rows[0]["publisher"], rows[1]["publisher"] = "held", "development"
    parts = stress_partitions(rows, publishers=["held"])
    assert rows[0] in parts["quarantine"] and rows[1] in parts["quarantine"]
    rows[2]["published_at"] = None
    time_parts = stress_partitions(rows, cutoff="2026-11-15T00:00:00Z")
    assert rows[2] in time_parts["quarantine"]


def test_export_cannot_feed_legacy_trainer(dataset_case):
    from src.training_manifest import validate_training_manifest
    root, store, path = dataset_case
    export_dataset(store, path, root / "dataset")
    with pytest.raises(ValueError, match="Unsupported/malformed training manifest"):
        validate_training_manifest(root / "dataset/manifest.json", root / "dataset")
