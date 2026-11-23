"""Ranking diagnostics against current human global approvals only."""
import argparse
from pathlib import Path

from .content_reference import load_source
from .global_discovery import load_ranking
from .global_io import digest, encoded, publish_directory
from .global_review import history
from .global_taxonomy import load_taxonomy
from .global_discovery import TAXONOMY


def benchmark(ranking, store, k=10, domain="defense", event_type=None):
    if type(k) is not int or k < 1:
        raise ValueError("K must be positive")
    taxonomy = load_taxonomy(TAXONOMY)
    if domain not in taxonomy["domains"] or (event_type is not None and event_type not in taxonomy["defense_event_types"]):
        raise ValueError("Unknown benchmark domain/event type")
    manifest, rows = load_ranking(ranking)
    approvals, heads = history(store)
    reviewed, approval_ids, stale = {}, [], 0
    for ident in heads.values():
        approval = approvals[ident]
        ref, _, _ = load_source(store, approval["source"]["source_ref_id"])
        tax = approval["documents"]["taxonomy"]
        if domain not in tax["domains"] or (event_type is not None and event_type not in tax["defense_event_types"]):
            raise ValueError("Unknown benchmark domain/event type")
        reviewed[ref["canonical_source_id"]] = (approval, ref)
    labels = {}
    for row in rows:
        pair = reviewed.get(row["source_id"])
        if pair is None:
            continue
        approval, ref = pair
        revision = row["ranking"]["article_revision"]
        matches = (revision["source_binding"] == approval["source"] if revision["basis"] == "registered_content"
                   else revision["ranking_text_sha256"] == digest(ref["metadata"]["article_title"].strip().encode()))
        if not matches:
            stale += 1
            continue
        labels[row["candidate_id"]] = (event_type in approval["annotation"]["defense_event_types"] if event_type
                                       else domain in approval["annotation"]["domains"])
        approval_ids.append(approval["approval_id"])
    complete = len(labels) == len(rows)
    positives = sum(labels.values())
    results = {}
    for strategy, field in (("keyword", "keyword_score"), ("semantic", "semantic_score"), ("hybrid", "hybrid_score")):
        top = sorted(rows, key=lambda r: (-r["ranking"][field], r["source_id"]))[:k]
        known = [labels[r["candidate_id"]] for r in top if r["candidate_id"] in labels]
        results[strategy] = {"k": k, "available_at_k": len(top), "reviewed_at_k": len(known), "positive_at_k": sum(known),
                             "precision_at_k": sum(known) / k if len(top) == k and len(known) == k else None,
                             "precision_reason": "fewer_than_k_candidates" if len(top) < k else "unreviewed_top_k" if len(known) < k else None,
                             "recall_at_k": sum(known) / positives if complete and positives else None,
                             "recall_reason": "incomplete_reviewed_pool" if not complete else "no_reviewed_positives" if not positives else None}
    return {"schema_version": "aic-global-ranking-benchmark-v1", "domain": domain, "event_type": event_type,
            "ranking_manifest_sha256": digest((Path(ranking) / "manifest.json").read_bytes()), "approval_ids": sorted(approval_ids),
            "candidate_pool": len(rows), "human_reviewed": len(labels), "stale_review_matches": stale,
            "unreviewed_not_negative": len(rows) - len(labels), "reviewed_positives": positives,
            "recall_denominator_defined": complete and positives > 0, "recall_scope": "fully_reviewed_candidate_pool_only",
            "metrics": results, "insufficiency": None if complete and positives else "Incomplete human-review denominator or no positive examples"}


def main():
    parser = argparse.ArgumentParser(description="Compare ranking against human-approved global labels; unknown is never negative")
    parser.add_argument("--ranking", type=Path, required=True)
    parser.add_argument("--store", type=Path, default=Path("data/global_annotations"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--domain", default="defense")
    parser.add_argument("--event-type")
    args = parser.parse_args()
    result = benchmark(args.ranking, args.store, args.k, args.domain, args.event_type)
    publish_directory(args.output, {"benchmark.json": encoded(result)})
    print(encoded(result).decode())


if __name__ == "__main__":
    main()
