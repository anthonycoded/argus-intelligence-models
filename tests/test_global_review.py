import builtins
from copy import deepcopy
import json
import sys

import pytest

from src.content_reference import load_source, register_source
from src.global_io import digest, encoded, read_object
from src.global_review import (approve, attest_rights, create_draft, eligibility_report, history,
                               load_approval, load_draft, revise)


def draft(c):
    return create_draft(c["root"], c["source"], c["annotation"])


def approved(c):
    return approve(c["root"], draft(c), "human-test-reviewer", True)


def test_approval_requires_explicit_confirmation_and_reviewer(global_case):
    c = global_case
    ident = draft(c)
    with pytest.raises(ValueError, match="confirm-human-review"):
        approve(c["root"], ident, "reviewer")
    with pytest.raises(ValueError, match="reviewer identity"):
        approve(c["root"], ident, "", True)
    assert not (c["root"] / "approvals").exists()


def test_immutable_versioned_approval_envelope(global_case):
    c = global_case
    ident = approved(c)
    envelope = load_approval(c["root"], ident)
    assert envelope["revision"] == 1 and envelope["supersedes"] is None
    assert envelope["taxonomy_version"] == "aic-global-v2"
    assert envelope["annotation_policy_version"] == "aic-global-review-v1"
    assert envelope["reviewed_at"].endswith("+00:00")
    assert len(envelope["taxonomy_sha256"]) == len(envelope["annotation_policy_sha256"]) == 64
    assert envelope["content_revision_sha256"] == digest(c["text"].encode())
    assert envelope["reviewed_by"] == "human-test-reviewer"


def test_duplicate_approval_and_duplicate_roots_rejected(global_case):
    c = global_case
    d = draft(c)
    ident = approve(c["root"], d, "reviewer", True)
    path = c["root"] / "approvals" / ident / "approval.json"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="already approved"):
        approve(c["root"], d, "another-reviewer", True)
    with pytest.raises(ValueError, match="explicit revision"):
        draft(c)
    assert path.read_bytes() == before


def test_concurrent_pending_roots_cannot_both_be_approved(global_case):
    c = global_case
    first, second = draft(c), draft(c)
    approve(c["root"], first, "reviewer", True)
    with pytest.raises(ValueError, match="explicit revision"):
        approve(c["root"], second, "reviewer", True)


@pytest.mark.parametrize("filename", ["content.utf8", "provenance.json", "reference.json"])
def test_stale_content_or_provenance_rejected_at_approval(global_case, filename):
    c = global_case
    d = draft(c)
    path = c["root"] / "sources" / c["source"] / filename
    if filename == "content.utf8":
        path.write_bytes(path.read_bytes().upper())
    else:
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        approve(c["root"], d, "reviewer", True)
    assert not (c["root"] / "approvals").exists()


@pytest.mark.parametrize("artifact,filename,id_field", [("drafts", "draft.json", "draft_id"), ("approvals", "approval.json", "approval_id")])
def test_forged_artifact_cannot_be_loaded(global_case, artifact, filename, id_field):
    c = global_case
    ident = draft(c) if artifact == "drafts" else approved(c)
    path = c["root"] / artifact / ident / filename
    obj = read_object(path)
    obj["annotation"]["rationale"] = "Forged replacement rationale"
    path.write_bytes(encoded(obj))
    with pytest.raises(ValueError, match="identity/hash mismatch"):
        (load_draft if artifact == "drafts" else load_approval)(c["root"], ident)


def test_revisions_preserve_history_and_reject_stale_branches(global_case):
    c = global_case
    first = approved(c)
    first_path = c["root"] / "approvals" / first / "approval.json"
    before = first_path.read_bytes()
    changed = deepcopy(c["annotation"])
    changed["rationale"] = "Corrected reviewer rationale"
    d1, d2 = revise(c["root"], first, changed), revise(c["root"], first, changed)
    second = approve(c["root"], d1, "second-reviewer", True)
    assert load_approval(c["root"], second)["supersedes"] == first
    assert load_approval(c["root"], second)["revision"] == 2
    assert first_path.read_bytes() == before
    assert len(history(c["root"])[0]) == 2
    with pytest.raises(ValueError, match="current approval head"):
        approve(c["root"], d2, "reviewer", True)
    with pytest.raises(ValueError, match="current approval head"):
        revise(c["root"], first, changed)


def test_revision_can_bind_new_content_without_rewriting_old_revision(global_case):
    c = global_case
    first = approved(c)
    old_bytes = (c["root"] / "sources" / c["source"] / "content.utf8").read_bytes()
    c["text_file"].write_bytes(c["text"].replace("2026-11-20", "2026-11-21").encode())
    source2 = register_source(c["root"], c["metadata"], c["text_file"])
    changed = c["article_for"](source2)
    d = revise(c["root"], first, changed, source_ref_id=source2)
    second = approve(c["root"], d, "reviewer", True)
    assert load_approval(c["root"], first)["source"]["source_ref_id"] == c["source"]
    assert load_approval(c["root"], second)["source"]["source_ref_id"] == source2
    assert (c["root"] / "sources" / c["source"] / "content.utf8").read_bytes() == old_bytes
    assert not eligibility_report(c["root"])["sources"][c["source"]]["annotation_approved"]


def test_revision_cannot_change_article_identity(global_case):
    c = global_case
    first = approved(c)
    metadata = {**c["metadata"], "source_id": "https://example.org/different-article"}
    source2 = register_source(c["root"], metadata, c["text_file"])
    with pytest.raises(ValueError, match="current approval head"):
        revise(c["root"], first, c["article_for"](source2), source2)


def test_approval_and_rights_are_independent(global_case):
    c = global_case
    ident = approved(c)
    report = eligibility_report(c["root"])
    assert report["sources"][c["source"]]["annotation_approved"]
    assert report["sources"][c["source"]]["rights_status"] == "unverified"
    assert report["eligible_for_future_dataset"] == 0
    attest_rights(c["root"], c["source"], "cleared", "Synthetic permission only", "rights-reviewer", True)
    report = eligibility_report(c["root"])
    assert report["eligible_for_future_dataset"] == 1
    assert not report["training_ready"] and not report["global_training_export_supported"]
    assert load_approval(c["root"], ident)["approval_id"] == ident


def test_rights_clearance_does_not_approve_annotation(global_case):
    c = global_case
    attest_rights(c["root"], c["source"], "cleared", "Synthetic permission only", "reviewer", True)
    report = eligibility_report(c["root"])
    assert report["sources"][c["source"]]["rights_status"] == "cleared"
    assert report["eligible_for_future_dataset"] == 0


def test_rights_requires_separate_confirmation(global_case):
    c = global_case
    with pytest.raises(ValueError, match="confirm-rights-review"):
        attest_rights(c["root"], c["source"], "cleared", "basis", "reviewer")
    assert not (c["root"] / "rights").exists()


@pytest.mark.parametrize("status", ["restricted", "unverified"])
def test_restricted_or_unverified_rights_block_approved_data(global_case, status):
    c = global_case
    approved(c)
    attest_rights(c["root"], c["source"], status, "Synthetic review", "reviewer", True)
    report = eligibility_report(c["root"])
    assert report["sources"][c["source"]]["annotation_approved"]
    assert not report["eligible_for_future_dataset"]


def test_rights_conflict_never_selects_latest_clearance(global_case):
    c = global_case
    approved(c)
    for status in ("restricted", "cleared"):
        attest_rights(c["root"], c["source"], status, "Synthetic decisions", "reviewer", True)
    report = eligibility_report(c["root"])
    assert report["sources"][c["source"]]["rights_status"] == "conflicting_decisions"
    assert not report["eligible_for_future_dataset"]


def test_corrupted_history_blocks_all_global_eligibility(global_case):
    c = global_case
    ident = approved(c)
    path = c["root"] / "approvals" / ident / "approval.json"
    obj = read_object(path)
    obj["reviewed_by"] = "forged"
    path.write_bytes(encoded(obj))
    report = eligibility_report(c["root"])
    assert not report["approval_store_valid"] and not report["eligible_for_future_dataset"]
    with pytest.raises(ValueError):
        history(c["root"])


def test_current_policy_change_rejects_draft_but_keeps_archived_approval(global_case, tmp_path):
    c = global_case
    ident = approved(c)
    draft2 = revise(c["root"], ident, c["annotation"])
    policy = deepcopy(c["policy"])
    policy["guidance"] += " Changed guidance requires another draft."
    path = tmp_path / "changed-policy.json"
    path.write_bytes(encoded(policy))
    with pytest.raises(ValueError, match="Stale draft"):
        approve(c["root"], draft2, "reviewer", True, policy=path)
    assert load_approval(c["root"], ident)["approval_id"] == ident


def test_global_envelopes_are_not_accepted_by_phase2l_trainer(global_case):
    from src.training_manifest import validate_training_manifest
    c = global_case
    ident = approved(c)
    with pytest.raises(ValueError, match="Unsupported/malformed training manifest"):
        validate_training_manifest(c["root"] / "approvals" / ident / "approval.json", c["root"])


def test_global_cli_end_to_end_and_no_model_imports(global_case, tmp_path, monkeypatch, capsys):
    c = global_case
    annotation = tmp_path / "annotation.json"
    annotation.write_bytes(encoded(c["annotation"]))
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "transformers", "sentence_transformers", "datasets"}:
            pytest.fail("Global review imported a model/training dependency")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    def invoke(*args):
        monkeypatch.setattr(sys, "argv", ["global_review", "--store", str(c["root"]), *map(str, args)])
        # Import main normally; no runpy duplicate-module warning.
        from src.global_review import main
        main()
        return json.loads(capsys.readouterr().out)

    d = invoke("draft", c["source"], annotation)["draft_id"]
    assert invoke("review", d)["content_path"].endswith("content.utf8")
    a = invoke("approve", d, "--reviewer", "cli-reviewer", "--confirm-human-review")["approval_id"]
    assert a in invoke("history")
    assert invoke("eligibility")["eligible_for_future_dataset"] == 0
    assert invoke("revise", a, annotation)["draft_id"]
