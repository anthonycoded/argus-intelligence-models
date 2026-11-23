"""Regression tests use synthetic approvals/rights only, entirely under tmp_path."""
import builtins
import hashlib
import json
import runpy
import sys
from pathlib import Path

import pytest

from src.candidate_import import fingerprint
from src.dataset_integrity import attest_rights, snapshot_report
from src.schema import LABELS
from src.split_dataset import leakage_components, split_grouped, validate_partitions
from src.training_manifest import (create_snapshot, freeze_splits,
                                   validate_snapshot, validate_training_manifest)


def rows(n=36):
    return [{"record_id": f"aic1-{i:032x}", "event_group_id": f"event-{i}",
             "source_id": f"https://example.org/{i}", "collected_at": "2026-11-22T00:00:00Z",
             "topic": "Chinese military activity near Taiwan", "topic_id": "taiwan-military",
             "subject_spec": "Synthetic requirements", "article_title": f"Synthetic report {i}",
             "article_text": f"Independent synthetic source content {i}", "label": LABELS[i % 3],
             "label_source": "human_verified", "rationale": "Synthetic human fixture",
             "annotation_version": "v1.1", "annotation_policy_version": "aic1-taiwan-v2",
             "criteria": {k: {"assessment": a, "evidence": "Synthetic test evidence"} for k, a in
                          [("mandatory_subject", "met"), ("geography", "met"),
                           ("material_connection", "met"), ("exclusion", "not_met")]}}
            for i in range(n)]


def write_rows(path, data):
    path.write_text("".join(json.dumps(r) + "\n" for r in data), encoding="utf-8")


def write_json(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


@pytest.fixture
def store(tmp_path):
    approved, prov, reviews, topic = (tmp_path / "approved.jsonl", tmp_path / "provenance",
                                       tmp_path / "reviews", tmp_path / "topic.json")
    prov.mkdir()
    reviews.mkdir()
    topic.write_bytes(Path("topics/taiwan_military_v2.json").read_bytes())
    data = rows()
    write_rows(approved, data)
    for row in data:
        write_json(prov / f"{row['record_id']}.json",
                   {"record_id": row["record_id"], "canonical_source_id": row["source_id"],
                    "text_sha256": fingerprint(row["article_text"]), "content_type": "human_summary",
                    "rights_status": "unverified"})
        attest_rights(row["record_id"], "cleared", "Synthetic test content only", "human_summary",
                      "synthetic-reviewer", approved, prov)
    return approved, prov, reviews, topic


def bundle(store, root):
    snapshot = create_snapshot(*store, root / "snapshot")
    splits = freeze_splits(root / "snapshot/snapshot.jsonl", snapshot, root / "splits", seed=17)
    return snapshot, splits


def test_frozen_workflow_and_readiness(store, tmp_path):
    snapshot, manifest = bundle(store, tmp_path)
    parts = validate_training_manifest(manifest, tmp_path / "splits")
    assert sum(map(len, parts.values())) == 36
    validate_partitions(parts)
    # Training uses derived requirements without mutating source annotations.
    assert parts["train"][0]["subject_spec"].startswith("Mandatory subject:")
    assert json.loads(store[0].read_text().splitlines()[0])["subject_spec"] == "Synthetic requirements"
    report, _ = snapshot_report(*store)
    assert report["snapshot_eligible"] and report["split_ready"]
    assert not report["training_ready"] and report["training_manifest_required"]


def test_small_eligible_snapshot_is_not_training_ready(store, tmp_path):
    data = rows(1)
    write_rows(store[0], data)
    snapshot = create_snapshot(*store, tmp_path / "snapshot")
    assert len(validate_snapshot(snapshot)[0]) == 1
    report, _ = snapshot_report(*store)
    assert report["snapshot_eligible"] and not report["split_ready"]
    with pytest.raises(ValueError, match="at least 30"):
        freeze_splits(tmp_path / "snapshot/snapshot.jsonl", snapshot, tmp_path / "splits")
    assert not (tmp_path / "splits").exists()


@pytest.mark.parametrize("target", ["approved", "topic", "provenance", "rights", "snapshot", "train", "validation", "test"])
def test_changed_frozen_inputs_rejected(store, tmp_path, target):
    snapshot, manifest = bundle(store, tmp_path)
    locations = {"approved": store[0], "topic": store[3], "snapshot": tmp_path / "snapshot/snapshot.jsonl",
                 "provenance": next(store[1].glob("*.json")),
                 "rights": next((store[1] / "rights_decisions").glob("*.json"))}
    path = locations.get(target, tmp_path / f"splits/{target}.jsonl")
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="validation failed"):
        validate_training_manifest(manifest, tmp_path / "splits")


@pytest.mark.parametrize("mutation", ["missing", "restricted", "conflict", "wrong_record", "wrong_content", "no_reviewer", "no_timestamp"])
def test_rights_fail_closed_after_freeze(store, tmp_path, mutation):
    _, manifest = bundle(store, tmp_path)
    decision_path = next((store[1] / "rights_decisions").glob("*.json"))
    decision = json.loads(decision_path.read_text())
    if mutation == "missing":
        decision_path.unlink()
    elif mutation == "conflict":
        write_json(decision_path.with_name(decision_path.stem + "-second.json"), decision)
    else:
        field, value = {"restricted": ("rights_status", "restricted"), "wrong_record": ("record_id", "wrong"),
                        "wrong_content": ("content_sha256", "0" * 64), "no_reviewer": ("attested_by", ""),
                        "no_timestamp": ("attested_at", None)}[mutation]
        decision[field] = value
        write_json(decision_path, decision)
    with pytest.raises(ValueError, match="validation failed"):
        validate_training_manifest(manifest, tmp_path / "splits")


def test_human_verified_and_base_cleared_are_insufficient(store, tmp_path):
    for path in (store[1] / "rights_decisions").glob("*.json"):
        path.unlink()
    for path in store[1].glob("*.json"):
        obj = json.loads(path.read_text())
        obj["rights_status"] = "cleared"
        write_json(path, obj)
    with pytest.raises(ValueError, match="explicit rights decision"):
        create_snapshot(*store, tmp_path / "snapshot")
    assert not (tmp_path / "snapshot").exists()


def test_frozen_outputs_never_overwritten(store, tmp_path):
    snapshot, manifest = bundle(store, tmp_path)
    before = manifest.read_bytes()
    with pytest.raises(FileExistsError):
        create_snapshot(*store, tmp_path / "snapshot")
    with pytest.raises(FileExistsError):
        freeze_splits(tmp_path / "snapshot/snapshot.jsonl", snapshot, tmp_path / "splits")
    assert manifest.read_bytes() == before


@pytest.mark.parametrize("malformed", [None, {}, [], {"schema_version": 1}, {"schema_version": True}])
def test_malformed_manifests_rejected(tmp_path, malformed):
    path = tmp_path / "manifest.json"
    write_json(path, malformed)
    with pytest.raises(ValueError, match="validation failed"):
        validate_training_manifest(path, tmp_path)


@pytest.mark.parametrize("entry", ["src.train", "main"])
@pytest.mark.parametrize("case", ["missing_argument", "missing_file", "malformed", "ineligible", "test_tampered", "wrong_data_dir"])
def test_entry_points_fail_before_ml_import(store, tmp_path, monkeypatch, entry, case):
    manifest = tmp_path / "missing.json"
    if case == "malformed":
        manifest.write_text("{broken", encoding="utf-8")
    if case in ("ineligible", "test_tampered", "wrong_data_dir"):
        _, manifest = bundle(store, tmp_path)
    if case == "ineligible":
        rights = next((store[1] / "rights_decisions").glob("*.json"))
        decision = json.loads(rights.read_text())
        decision["rights_status"] = "restricted"
        write_json(rights, decision)
    if case == "test_tampered":
        with (tmp_path / "splits/test.jsonl").open("ab") as handle:
            handle.write(b" ")
    original = builtins.__import__

    def guard(name, *args, **kwargs):
        if name.split(".")[0] in {"transformers", "torch", "datasets", "numpy", "sklearn"}:
            pytest.fail(f"ML imported before eligibility validation: {name}")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    monkeypatch.delitem(sys.modules, "src.train", raising=False)
    argv = [entry, "--data", str(tmp_path / ("wrong" if case == "wrong_data_dir" else "splits"))]
    if case != "missing_argument":
        argv += ["--manifest", str(manifest)]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises((ValueError, SystemExit)):
        runpy.run_module(entry, run_name="__main__")


def test_main_import_has_no_training_side_effect(monkeypatch):
    import importlib.util
    original = builtins.__import__

    def guard(name, *args, **kwargs):
        if name == "src.train" or name.split(".")[0] in {"transformers", "torch", "datasets"}:
            pytest.fail("main.py import attempted training initialization")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    spec = importlib.util.spec_from_file_location("legacy_main_probe", "main.py")
    spec.loader.exec_module(importlib.util.module_from_spec(spec))


def test_split_ratios_and_order_independent_determinism():
    data = rows(300)
    first = split_grouped(data, seed=7)
    assert first == split_grouped(list(reversed(data)), seed=7)
    assert [len(first[s]) for s in ("train", "validation", "test")] == [210, 45, 45]
    assert first != split_grouped(data, seed=8)


@pytest.mark.parametrize("field", ["event_group_id", "source_id", "article_text", "duplicate_group_id", "known_duplicate_group_id"])
def test_shared_identities_never_cross_splits(field):
    data = rows(90)
    data[0][field] = data[3].get(field, "shared-group")
    data[3][field] = data[0][field]
    parts = split_grouped(data)
    locations = {r["record_id"]: s for s, part in parts.items() for r in part}
    assert locations[data[0]["record_id"]] == locations[data[3]["record_id"]]


def test_transitive_duplicates_merge():
    data = rows(3)
    data[1]["source_id"] = data[0]["source_id"] + "?utm_source=test"
    data[2]["article_text"] = data[1]["article_text"].upper()
    assert len(leakage_components(data)) == 1


def test_duplicate_records_and_insufficient_independent_groups_rejected():
    data = rows()
    with pytest.raises(ValueError, match="Duplicate record_id"):
        split_grouped(data + [data[0]])
    for row in data:
        row["article_text"] = "All copies of one report"
    with pytest.raises(ValueError, match="independent leakage groups"):
        split_grouped(data)


@pytest.mark.parametrize("field", ["record_id", "event_group_id", "source_id", "article_text", "known_duplicate_group_id"])
def test_partition_validation_detects_leakage(field):
    parts = split_grouped(rows(90))
    parts["train"][0][field] = parts["test"][0].get(field, "shared")
    parts["test"][0][field] = parts["train"][0][field]
    with pytest.raises(ValueError, match="leakage/duplicate"):
        validate_partitions(parts)


def test_missing_label_support_rejected():
    data = rows()
    data = [r for r in data if r["label"] != "relevant"]
    data += rows(90)[36:66]
    data = [r for r in data if r["label"] != "relevant"]
    with pytest.raises(ValueError, match="containing relevant"):
        split_grouped(data)


def test_rehashed_split_annotation_still_rejected(store, tmp_path):
    _, manifest = bundle(store, tmp_path)
    obj = json.loads(manifest.read_text())
    path = tmp_path / "splits/train.jsonl"
    data = [json.loads(l) for l in path.read_text().splitlines()]
    data[0]["rationale"] = "Unauthorized changed annotation"
    write_rows(path, data)
    obj["splits"]["train"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(manifest, obj)
    with pytest.raises(ValueError, match="membership/annotation"):
        validate_training_manifest(manifest, tmp_path / "splits")


def test_duplicate_json_manifest_keys_rejected(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        validate_training_manifest(path, tmp_path)


def test_policy_review_bound_to_original_and_rechecked(store, tmp_path):
    from src.dataset_integrity import submit_policy_review
    data = rows()
    data[0]["annotation_policy_version"] = "aic1-taiwan-v1"
    write_rows(store[0], data)
    # Rebuild only synthetic test rights for the altered source annotation.
    for p in (store[1] / "rights_decisions").glob(f"{data[0]['record_id']}-*.json"):
        p.unlink()
    attest_rights(data[0]["record_id"], "cleared", "Synthetic test only", "human_summary", "tester", store[0], store[1])
    review_input = tmp_path / "review.json"
    write_json(review_input, {k: data[0][k] for k in ("label", "rationale", "criteria")})
    submit_policy_review(data[0]["record_id"], review_input, store[0], store[3], store[2], "tester", True)
    _, manifest = bundle(store, tmp_path)
    assert validate_training_manifest(manifest, tmp_path / "splits")
    path = next(store[2].glob("*.json"))
    obj = json.loads(path.read_text())
    obj["source_record_hash"] = "0" * 64
    write_json(path, obj)
    with pytest.raises(ValueError, match="policy review"):
        validate_training_manifest(manifest, tmp_path / "splits")


def test_snapshot_path_mismatch_rejected(store, tmp_path):
    snapshot = create_snapshot(*store, tmp_path / "snapshot")
    with pytest.raises(ValueError, match="Input does not match"):
        freeze_splits(tmp_path / "other.jsonl", snapshot, tmp_path / "splits")


@pytest.mark.parametrize("mutation", ["label", "source_id", "article_text", "record_id"])
def test_rehashed_snapshot_cannot_replace_approved_identity(store, tmp_path, mutation):
    snapshot = create_snapshot(*store, tmp_path / "snapshot")
    obj = json.loads(snapshot.read_text())
    path = tmp_path / "snapshot/snapshot.jsonl"
    data = [json.loads(l) for l in path.read_text().splitlines()]
    data[0][mutation] = {"label": "relevant", "source_id": "https://example.org/changed",
                         "article_text": "Different content", "record_id": "aic1-" + "f" * 32}[mutation]
    write_rows(path, data)
    obj["snapshot"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(snapshot, obj)
    with pytest.raises(ValueError, match="validation failed"):
        validate_snapshot(snapshot)


def test_missing_split_label_support_rejected():
    parts = split_grouped(rows(90))
    parts["test"] = [r for r in parts["test"] if r["label"] != "relevant"]
    with pytest.raises(ValueError, match="every label requires support"):
        validate_partitions(parts)


def test_empty_eligibility_does_not_publish_snapshot(store, tmp_path):
    for p in (store[1] / "rights_decisions").glob("*.json"):
        p.unlink()
    with pytest.raises(ValueError, match="No eligible records"):
        create_snapshot(*store, tmp_path / "snapshot")
    assert not (tmp_path / "snapshot").exists()


def test_legacy_eligibility_boolean_cannot_freeze(tmp_path):
    from src.dataset_integrity import freeze_snapshot
    with pytest.raises(ValueError, match="Legacy snapshot"):
        freeze_snapshot({"training_ready": True}, rows(), tmp_path / "legacy")
    assert not (tmp_path / "legacy").exists()


def test_exact_content_binding_survives_rehashed_file_references(store, tmp_path):
    snapshot, manifest = bundle(store, tmp_path)
    data = rows()
    data[0]["article_text"] = data[0]["article_text"].upper()
    assert fingerprint(data[0]["article_text"]) == fingerprint(rows()[0]["article_text"])
    write_rows(store[0], data)
    obj = json.loads(snapshot.read_text())
    obj["approved"]["sha256"] = hashlib.sha256(store[0].read_bytes()).hexdigest()
    write_json(snapshot, obj)
    obj = json.loads(manifest.read_text())
    obj["snapshot_manifest"]["sha256"] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    write_json(manifest, obj)
    with pytest.raises(ValueError, match="rights identity/content mismatch"):
        validate_training_manifest(manifest, tmp_path / "splits")


@pytest.mark.parametrize("entry", ["src.train", "main"])
def test_valid_manifest_reaches_ml_boundary_without_loading_models(store, tmp_path, monkeypatch, entry):
    _, manifest = bundle(store, tmp_path)
    original = builtins.__import__

    class ValidatedBoundary(Exception):
        pass

    def guard(name, *args, **kwargs):
        if name.split(".")[0] in {"numpy", "datasets", "transformers", "torch", "sklearn"}:
            raise ValidatedBoundary
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    monkeypatch.delitem(sys.modules, "src.train", raising=False)
    monkeypatch.setattr(sys, "argv", [entry, "--data", str(tmp_path / "splits"), "--manifest", str(manifest)])
    with pytest.raises(ValidatedBoundary):
        runpy.run_module(entry, run_name="__main__")
