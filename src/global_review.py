"""Phase 2M local global annotation lifecycle; no training/export implementation."""
import argparse
from pathlib import Path

from .content_reference import (REPRESENTATIONS, check_binding, load_source, prepare_discovery,
                                register_source)
from .global_annotation_schema import validate_article, validate_documents
from .global_io import (digest, document_hash, encoded, identifier, keys, now,
                        publish_directory, read_object, string, timestamp)

DEFAULT_TAXONOMY = Path(__file__).resolve().parents[1] / "taxonomies/global_intelligence_v2.json"
DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "policies/global_annotation_v1.json"
DRAFT_FIELDS = {"schema_version", "draft_id", "annotation_id", "revision", "created_at", "source",
                "documents", "annotation", "supersedes"}
APPROVAL_FIELDS = {"schema_version", "approval_id", "annotation_id", "revision", "draft_id", "draft_sha256",
                   "source", "documents", "annotation", "supersedes", "reviewed_by", "reviewed_at",
                   "review_confirmation", "taxonomy_version", "taxonomy_sha256", "annotation_policy_version",
                   "annotation_policy_sha256", "content_revision_sha256"}
RIGHTS_FIELDS = {"schema_version", "decision_id", "source", "rights_status", "scope", "content_type",
                 "reviewed_by", "reviewed_at", "review_confirmation", "evidence"}


def _documents(taxonomy=DEFAULT_TAXONOMY, policy=DEFAULT_POLICY):
    docs = {"taxonomy": read_object(taxonomy), "policy": read_object(policy)}
    _validate_documents(docs)
    return docs


def _validate_documents(docs):
    keys(docs, {"taxonomy", "policy"}, "annotation documents")
    validate_documents(docs["taxonomy"], docs["policy"])


def _family(canonical_source):
    return "ann-" + digest(canonical_source.encode("utf-8"))


def _artifact_id(obj, field, prefix):
    return prefix + document_hash({k: v for k, v in obj.items() if k != field})


def _load_artifact(root, directory, ident, prefix, filename):
    identifier(ident, prefix)
    path = Path(root) / directory / ident / filename
    obj = read_object(path)
    field = {"draft-": "draft_id", "approval-": "approval_id", "rights-": "decision_id"}[prefix]
    if obj.get(field) != ident or _artifact_id(obj, field, prefix) != ident:
        raise ValueError(f"Immutable {directory} artifact identity/hash mismatch")
    return obj, path


def load_draft(root, draft_id):
    draft, _ = _load_artifact(root, "drafts", draft_id, "draft-", "draft.json")
    keys(draft, DRAFT_FIELDS, "global draft")
    if draft["schema_version"] != "aic-global-draft-v1" or type(draft["revision"]) is not int or draft["revision"] < 1:
        raise ValueError("Unsupported draft schema/revision")
    timestamp(draft["created_at"], "created_at", utc=True)
    _validate_documents(draft["documents"])
    ref, text = check_binding(root, draft["source"])
    if draft["annotation_id"] != _family(ref["canonical_source_id"]):
        raise ValueError("Draft annotation/source family mismatch")
    if draft["supersedes"] is not None:
        identifier(draft["supersedes"], "approval-")
    validate_article(draft["annotation"], draft["documents"]["taxonomy"], draft["documents"]["policy"],
                     text, ref["content_revision_sha256"])
    return draft


def load_approval(root, approval_id):
    approval, _ = _load_artifact(root, "approvals", approval_id, "approval-", "approval.json")
    keys(approval, APPROVAL_FIELDS, "global approval")
    if approval["schema_version"] != "aic-global-approval-v1" or approval["review_confirmation"] is not True:
        raise ValueError("Unsupported/unconfirmed global approval")
    string(approval["reviewed_by"], "reviewed_by")
    timestamp(approval["reviewed_at"], "reviewed_at", utc=True)
    draft = load_draft(root, approval["draft_id"])
    draft_path = Path(root) / "drafts" / approval["draft_id"] / "draft.json"
    if approval["draft_sha256"] != digest(draft_path.read_bytes()):
        raise ValueError("Approved draft identity mismatch")
    for field in ("annotation_id", "revision", "source", "documents", "annotation", "supersedes"):
        if approval[field] != draft[field]:
            raise ValueError(f"Approval/draft {field} mismatch")
    docs = approval["documents"]
    if (approval["taxonomy_version"] != docs["taxonomy"]["version"]
            or approval["taxonomy_sha256"] != document_hash(docs["taxonomy"])
            or approval["annotation_policy_version"] != docs["policy"]["policy_version"]
            or approval["annotation_policy_sha256"] != document_hash(docs["policy"])
            or approval["content_revision_sha256"] != approval["source"]["content_revision_sha256"]):
        raise ValueError("Approval document/content hash mismatch")
    return approval


def history(root):
    """Verify complete immutable history and reject duplicate roots/forks/gaps."""
    approvals, heads, children, used_drafts = {}, {}, set(), set()
    directory = Path(root) / "approvals"
    for entry in sorted(directory.iterdir()) if directory.exists() else []:
        approval = load_approval(root, entry.name)
        if approval["draft_id"] in used_drafts:
            raise ValueError("Duplicate approval for one draft")
        used_drafts.add(approval["draft_id"])
        approvals[approval["approval_id"]] = approval
    for approval in sorted(approvals.values(), key=lambda a: a["revision"]):
        family, parent = approval["annotation_id"], approval["supersedes"]
        if parent is None:
            if approval["revision"] != 1 or family in heads:
                raise ValueError("Duplicate/malformed global approval root")
        else:
            previous = approvals.get(parent)
            if (previous is None or parent in children or previous["annotation_id"] != family
                    or approval["revision"] != previous["revision"] + 1 or heads.get(family) != parent):
                raise ValueError("Missing, stale or forked approval supersession")
            children.add(parent)
        heads[family] = approval["approval_id"]
    return approvals, heads


def _check_revision(draft, approvals, heads):
    parent, family = draft["supersedes"], draft["annotation_id"]
    if parent is None:
        if family in heads or draft["revision"] != 1:
            raise ValueError("Existing global approval; create an explicit revision")
    elif (parent not in approvals or heads.get(family) != parent
          or approvals[parent]["annotation_id"] != family or draft["revision"] != approvals[parent]["revision"] + 1):
        raise ValueError("Revision must supersede the current approval head")


def create_draft(root, source_ref_id, annotation, taxonomy=DEFAULT_TAXONOMY, policy=DEFAULT_POLICY, supersedes=None):
    ref, text, binding = load_source(root, source_ref_id)
    docs = _documents(taxonomy, policy)
    validate_article(annotation, docs["taxonomy"], docs["policy"], text, ref["content_revision_sha256"])
    approvals, heads = history(root)
    revision = 1
    if supersedes is not None:
        identifier(supersedes, "approval-")
        if supersedes not in approvals:
            raise ValueError("Unknown superseded approval")
        revision = approvals[supersedes]["revision"] + 1
    draft = {"schema_version": "aic-global-draft-v1", "annotation_id": _family(ref["canonical_source_id"]),
             "revision": revision, "created_at": now(), "source": binding, "documents": docs,
             "annotation": annotation, "supersedes": supersedes}
    _check_revision(draft, approvals, heads)
    draft["draft_id"] = _artifact_id(draft, "draft_id", "draft-")
    publish_directory(Path(root) / "drafts" / draft["draft_id"], {"draft.json": encoded(draft)})
    return draft["draft_id"]


def approve(root, draft_id, reviewer, confirm=False, taxonomy=DEFAULT_TAXONOMY, policy=DEFAULT_POLICY):
    if confirm is not True:
        raise ValueError("Explicit --confirm-human-review required")
    string(reviewer, "reviewer identity")
    draft = load_draft(root, draft_id)
    if draft["documents"] != _documents(taxonomy, policy):
        raise ValueError("Stale draft taxonomy/policy; create a new reviewed draft")
    approvals, heads = history(root)
    if any(a["draft_id"] == draft_id for a in approvals.values()):
        raise ValueError("Draft already approved")
    _check_revision(draft, approvals, heads)
    docs = draft["documents"]
    envelope = {"schema_version": "aic-global-approval-v1",
                **{k: draft[k] for k in ("annotation_id", "revision", "source", "documents", "annotation", "supersedes")},
                "draft_id": draft_id,
                "draft_sha256": digest((Path(root) / "drafts" / draft_id / "draft.json").read_bytes()),
                "reviewed_by": reviewer, "reviewed_at": now(), "review_confirmation": True,
                "taxonomy_version": docs["taxonomy"]["version"], "taxonomy_sha256": document_hash(docs["taxonomy"]),
                "annotation_policy_version": docs["policy"]["policy_version"],
                "annotation_policy_sha256": document_hash(docs["policy"]),
                "content_revision_sha256": draft["source"]["content_revision_sha256"]}
    envelope["approval_id"] = _artifact_id(envelope, "approval_id", "approval-")
    publish_directory(Path(root) / "approvals" / envelope["approval_id"], {"approval.json": encoded(envelope)})
    return envelope["approval_id"]


def revise(root, approval_id, annotation, source_ref_id=None, taxonomy=DEFAULT_TAXONOMY, policy=DEFAULT_POLICY):
    approvals, _ = history(root)
    if approval_id not in approvals:
        raise ValueError("Unknown approval to revise")
    source = source_ref_id or approvals[approval_id]["source"]["source_ref_id"]
    return create_draft(root, source, annotation, taxonomy, policy, supersedes=approval_id)


def attest_rights(root, source_ref_id, status, evidence, reviewer, confirm=False):
    """Separate explicit decision. Registration, accessibility and approval confer no rights."""
    if confirm is not True:
        raise ValueError("Explicit --confirm-rights-review required")
    if status not in {"unverified", "cleared", "restricted"}:
        raise ValueError("Unknown rights status")
    string(evidence, "rights evidence/basis")
    string(reviewer, "rights reviewer")
    ref, _, binding = load_source(root, source_ref_id)
    decision = {"schema_version": "aic-global-rights-v1", "source": binding, "rights_status": status,
                "scope": "model_training", "content_type": ref["metadata"]["content_type"],
                "reviewed_by": reviewer, "reviewed_at": now(), "review_confirmation": True, "evidence": evidence}
    decision["decision_id"] = _artifact_id(decision, "decision_id", "rights-")
    publish_directory(Path(root) / "rights" / source_ref_id / decision["decision_id"], {"decision.json": encoded(decision)})
    return decision["decision_id"]


def rights_status(root, source_ref_id):
    ref, _, binding = load_source(root, source_ref_id)
    directory = Path(root) / "rights" / source_ref_id
    entries = list(directory.iterdir()) if directory.exists() else []
    if not entries:
        return "unverified"
    if len(entries) != 1:
        return "conflicting_decisions"
    decision_id = entries[0].name
    decision, _ = _load_artifact(Path(root) / "rights", source_ref_id, decision_id, "rights-", "decision.json")
    keys(decision, RIGHTS_FIELDS, "global rights decision")
    if (decision["schema_version"] != "aic-global-rights-v1" or decision["source"] != binding
            or decision["scope"] != "model_training" or decision["content_type"] != ref["metadata"]["content_type"]
            or decision["rights_status"] not in {"unverified", "cleared", "restricted"}
            or decision["review_confirmation"] is not True):
        raise ValueError("Stale/mismatched rights identity or scope")
    string(decision["reviewed_by"], "rights reviewer")
    string(decision["evidence"], "rights evidence")
    timestamp(decision["reviewed_at"], "rights reviewed_at", utc=True)
    return decision["rights_status"]


def eligibility_report(root):
    """Approval/rights candidate eligibility only; no Phase 2L training contract is inferred."""
    report = {"approval_store_valid": True, "eligible_for_future_dataset": 0, "sources": {},
              "errors": [], "training_ready": False, "global_training_export_supported": False}
    try:
        approvals, heads = history(root)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        report.update(approval_store_valid=False, errors=[str(exc)])
        return report
    current = {approvals[ident]["source"]["source_ref_id"]: approvals[ident] for ident in heads.values()}
    directory = Path(root) / "sources"
    for path in sorted(directory.iterdir()) if directory.exists() else []:
        ident, reasons, status = path.name, [], "invalid"
        try:
            load_source(root, ident)
            status = rights_status(root, ident)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            reasons.append(str(exc))
        approval = current.get(ident)
        if approval is None:
            reasons.append("no_current_global_approval")
        if status != "cleared":
            reasons.append(f"rights_{status}")
        candidate = not reasons
        report["sources"][ident] = {"annotation_approved": approval is not None, "rights_status": status,
                                     "current_approval_id": approval["approval_id"] if approval else None,
                                     "eligible_for_future_dataset": candidate, "blocked": reasons}
        report["eligible_for_future_dataset"] += int(candidate)
    return report


def main():
    parser = argparse.ArgumentParser(description="Phase 2M global article annotation; offline, no model training")
    parser.add_argument("--store", type=Path, default=Path("data/global_annotations"))
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register")
    register.add_argument("metadata", type=Path)
    register.add_argument("--text-file", type=Path, required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("discovery_file", type=Path)
    prepare.add_argument("discovery_id")
    prepare.add_argument("--adapter", choices=("navy", "defensenews"), required=True)
    prepare.add_argument("--text-file", type=Path, required=True)
    prepare.add_argument("--content-type", choices=sorted(REPRESENTATIONS), required=True)
    prepare.add_argument("--rights-note", required=True)
    draft = commands.add_parser("draft")
    draft.add_argument("source_ref_id")
    draft.add_argument("annotation", type=Path)
    review = commands.add_parser("review")
    review.add_argument("draft_id")
    approval = commands.add_parser("approve")
    approval.add_argument("draft_id")
    approval.add_argument("--reviewer", required=True)
    approval.add_argument("--confirm-human-review", action="store_true")
    revision = commands.add_parser("revise")
    revision.add_argument("approval_id")
    revision.add_argument("annotation", type=Path)
    revision.add_argument("--source-ref")
    rights = commands.add_parser("rights")
    rights.add_argument("source_ref_id")
    rights.add_argument("--status", choices=("unverified", "cleared", "restricted"), required=True)
    rights.add_argument("--evidence", required=True)
    rights.add_argument("--reviewer", required=True)
    rights.add_argument("--confirm-rights-review", action="store_true")
    commands.add_parser("eligibility")
    commands.add_parser("history")
    args = parser.parse_args()
    try:
        if args.command == "register":
            result = {"source_ref_id": register_source(args.store, read_object(args.metadata), args.text_file)}
        elif args.command == "prepare":
            result = {"source_ref_id": prepare_discovery(args.store, args.discovery_file, args.discovery_id,
                       args.adapter, args.text_file, args.content_type, args.rights_note)}
        elif args.command == "draft":
            result = {"draft_id": create_draft(args.store, args.source_ref_id, read_object(args.annotation), args.taxonomy, args.policy)}
        elif args.command == "review":
            result = {"draft": load_draft(args.store, args.draft_id)}
            result["content_path"] = str(args.store / "sources" / result["draft"]["source"]["source_ref_id"] / "content.utf8")
        elif args.command == "approve":
            result = {"approval_id": approve(args.store, args.draft_id, args.reviewer, args.confirm_human_review, args.taxonomy, args.policy)}
        elif args.command == "revise":
            result = {"draft_id": revise(args.store, args.approval_id, read_object(args.annotation), args.source_ref, args.taxonomy, args.policy)}
        elif args.command == "rights":
            result = {"decision_id": attest_rights(args.store, args.source_ref_id, args.status, args.evidence,
                       args.reviewer, args.confirm_rights_review)}
        elif args.command == "history":
            result = history(args.store)[0]
        else:
            result = eligibility_report(args.store)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"Global annotation operation rejected: {exc}\n")
    print(encoded(result).decode("utf-8"))


if __name__ == "__main__":
    main()
