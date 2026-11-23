"""Reproducible diverse review sampling; query hints are NOT ground truth."""
import argparse
import os
from collections import Counter, defaultdict, deque
from pathlib import Path
import random

from .content_reference import load_source, register_source
from .global_discovery import load_ranking
from .global_feeds import REGIONS
from .global_io import digest, document_hash, encoded, keys, parse_json, publish_directory, read_object


def score_bucket(score):
    return "high" if score >= .6 else "middle" if score >= .3 else "low"


def diagnostics(rows, human=False):
    def counts(field, default="unknown"):
        return dict(sorted(Counter(r.get(field, default) for r in rows).items()))
    regions = Counter(region for row in rows for region in (row.get("regions", ["unknown"]) if human else [row.get("source_region", "unknown")]))
    result = {"records": len(rows), "publishers": counts("publisher"), "languages": counts("language"),
              "regions": dict(sorted(regions.items())), "region_basis": "human_cohort_metadata" if human else "source_metadata_assertions_not_event_geography_or_ground_truth",
              "missing_regions": sorted(REGIONS - {"unknown"} - set(regions)),
              "representativeness": "not_established", "human_annotated": human}
    if human:
        result["domains"] = dict(Counter(v for r in rows for v in r["domains"]))
        result["defense_event_types"] = dict(Counter(v for r in rows for v in r["defense_event_types"]))
        result["countries"] = dict(Counter(c["code"] for r in rows for c in r["annotation"]["countries"]))
        result["sampled_score_ranges"] = dict(Counter(r["sampling"]["selection"]["stratum"][-1] if r.get("sampling") else "not_recorded" for r in rows))
    else:
        result["unverified_query_hints"] = dict(Counter(r["ranking"]["query_hint"] for r in rows))
        result["score_ranges"] = dict(Counter(score_bucket(r["ranking"]["semantic_score"]) for r in rows))
        result["human_domain_coverage"] = "unmeasured; ranking hints are not labels"
    return result


def validate_sampling_config(config):
    keys(config, {"schema_version", "seed", "per_stratum", "publisher_cap", "region_cap", "max_total"}, "sampling config")
    if config["schema_version"] != "aic-global-sampling-v1" or type(config["seed"]) is not int:
        raise ValueError("Unsupported sampling configuration/seed")
    for field in ("per_stratum", "publisher_cap", "region_cap", "max_total"):
        if type(config[field]) is not int or not 1 <= config[field] <= 10000:
            raise ValueError("Sampling quotas must be positive bounded integers")


def select_candidates(rows, config):
    validate_sampling_config(config)
    strata = defaultdict(list)
    for row in rows:
        stratum = (row.get("source_region", "unknown"), row.get("publisher", "unknown"), row.get("language", "unknown"),
                   row["ranking"]["query_hint"], score_bucket(row["ranking"]["semantic_score"]))
        strata[stratum].append(row)
    queues, population, selected = {}, {}, []
    for stratum, members in sorted(strata.items()):
        members.sort(key=lambda r: r["candidate_id"])
        rng = random.Random(int(document_hash([config["seed"], stratum]), 16))
        queues[stratum] = deque(rng.sample(members, min(len(members), config["per_stratum"])))
        population[stratum] = len(members)
    order = sorted(queues)
    random.Random(config["seed"]).shuffle(order)
    order_rank = {s: i for i, s in enumerate(order)}
    publisher_counts, region_counts, bucket_counts, hint_counts = Counter(), Counter(), Counter(), Counter()
    constrained = False
    while any(queues.values()):
        available = [s for s in order if queues[s] and publisher_counts[s[1]] < config["publisher_cap"] and region_counts[s[0]] < config["region_cap"]]
        if not available or len(selected) >= config["max_total"]:
            constrained = True
            break
        stratum = min(available, key=lambda s: (region_counts[s[0]], publisher_counts[s[1]], bucket_counts[(s[1], s[-1])], hint_counts[(s[1], s[3])], order_rank[s]))
        row = queues[stratum].popleft()
        publisher_counts[stratum[1]] += 1
        region_counts[stratum[0]] += 1
        bucket_counts[(stratum[1], stratum[-1])] += 1
        hint_counts[(stratum[1], stratum[3])] += 1
        reasons = ["seeded_random_within_stratum", "balanced_region_publisher_score_hint_allocation"]
        if stratum[-1] == "low":
            reasons.append("randomized_low_score_exploration")
        if row["ranking"].get("language_status") == "unsupported_unvalidated":
            reasons.append("unsupported_language_requires_manual_review")
        meta = row["ranking"]
        if (meta["semantic_score"] >= .6 and meta["keyword_score"] == 0) or (meta["semantic_score"] < .3 and meta["keyword_score"] > 0):
            reasons.append("semantic_keyword_disagreement_hard_negative_candidate_not_label")
        probability = min(config["per_stratum"], population[stratum]) / population[stratum]
        selected.append({**row, "sampling": {"stratum": list(stratum), "population": population[stratum],
                         "first_stage_probability": probability, "inclusion_probability": probability,
                         "selection_reasons": reasons, "seed": config["seed"]}})
    if constrained:
        for row in selected:
            row["sampling"]["inclusion_probability"] = None
    selected.sort(key=lambda r: r["candidate_id"])
    return selected, {"caps_or_budget_applied": constrained,
                      "inclusion_probability_note": "Unknown after interacting caps/budget" if constrained else "Uniform without replacement within fixed strata",
                      "stratum_populations": [{"stratum": list(s), "population": n, "quota": config["per_stratum"]} for s, n in sorted(population.items())]}


def sample_ranking(ranking, output, config):
    manifest, rows = load_ranking(ranking)
    if manifest["mode"] != "global":
        raise ValueError("Global sampling requires global discovery; topic workflows remain separate")
    selected, design = select_candidates(rows, config)
    payload = b"".join(encoded(r) + b"\n" for r in selected)
    if len(payload) > 128 * 1024 * 1024:
        raise ValueError("Sample exceeds bounded pilot size")
    result = {"schema_version": "aic-global-review-sample-v1", "ranking_manifest_sha256": digest((Path(ranking) / "manifest.json").read_bytes()),
              "ranking_path": Path(os.path.relpath(Path(ranking).resolve(), Path(output).resolve())).as_posix(), "profile_sha256": document_hash(manifest["profile"]),
              "config": config, "design": design, "population": diagnostics(rows), "selected": diagnostics(selected),
              "sample_sha256": digest(payload)}
    publish_directory(output, {"sample.jsonl": payload, "manifest.json": encoded(result)})
    return result


def load_sample(directory):
    directory = Path(directory)
    obj = read_object(directory / "manifest.json")
    keys(obj, {"schema_version", "ranking_manifest_sha256", "ranking_path", "profile_sha256", "config", "design", "population", "selected", "sample_sha256"}, "sample manifest")
    if obj.get("schema_version") != "aic-global-review-sample-v1":
        raise ValueError("Unsupported sample manifest")
    ranking = (directory / obj["ranking_path"]).resolve()
    if digest((ranking / "manifest.json").read_bytes()) != obj["ranking_manifest_sha256"]:
        raise ValueError("Sample/ranking binding mismatch")
    ranking_manifest, rows = load_ranking(ranking)
    if ranking_manifest["mode"] != "global" or obj["profile_sha256"] != document_hash(ranking_manifest["profile"]):
        raise ValueError("Sample global profile identity mismatch")
    expected, design = select_candidates(rows, obj["config"])
    sample_file = directory / "sample.jsonl"
    if sample_file.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("Sample exceeds bounded pilot size")
    raw = sample_file.read_bytes()
    if (digest(raw) != obj["sample_sha256"] or raw != b"".join(encoded(r) + b"\n" for r in expected)
            or obj["design"] != design or obj["population"] != diagnostics(rows) or obj["selected"] != diagnostics(expected)):
        raise ValueError("Sample selection/configuration integrity mismatch")
    return obj, expected


def prepare_review(sample, candidate_id, store, text_file, content_type, rights_note):
    """Register human-supplied content and an intake receipt, with NO inferred labels."""
    manifest, selected = load_sample(sample)
    matches = [r for r in selected if r["candidate_id"] == candidate_id]
    if len(matches) != 1:
        raise ValueError("Candidate must be selected exactly once")
    row = matches[0]
    publisher = row.get("publisher")
    if not publisher:
        raise ValueError("Publisher metadata missing; register explicitly through Phase 2M")
    adapter = {"US Navy": "navy", "Defense News": "defensenews"}.get(publisher, "manual")
    metadata = {"source_id": row["source_id"], "publisher": publisher, "adapter": adapter,
                "article_title": row["article_title"], "published_at": row.get("published_at"), "published_at_raw": row.get("published_at_raw"),
                "collected_at": row["collected_at"], "content_type": content_type, "rights_note": rights_note,
                "provenance_method": "human_supplied_sampled_discovery"}
    ident = register_source(store, metadata, text_file)
    ref, _, binding = load_source(store, ident)
    receipt = {"schema_version": "aic-global-intake-v1", "state": "awaiting_human_global_draft", "source": binding,
               "candidate_id": candidate_id, "sample_path": str(Path(sample).resolve()),
               "sample_manifest_sha256": digest((Path(sample) / "manifest.json").read_bytes()),
               "sampling": row["sampling"], "inferred_annotations": None}
    receipt_id = "intake-" + document_hash(receipt)
    publish_directory(Path(store) / "intake" / receipt_id, {"receipt.json": encoded(receipt)})
    return {"source_ref_id": ident, "receipt_id": receipt_id, "next_step": "Create and explicitly approve a Phase 2M global draft"}


def main():
    parser = argparse.ArgumentParser(description="Diverse review sampling and Phase 2M intake; no machine labels")
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("sample")
    sample.add_argument("--ranking", type=Path, required=True)
    sample.add_argument("--output", type=Path, required=True)
    sample.add_argument("--seed", type=int, default=42)
    sample.add_argument("--per-stratum", type=int, default=2)
    sample.add_argument("--publisher-cap", type=int, default=8)
    sample.add_argument("--region-cap", type=int, default=40)
    sample.add_argument("--max-total", type=int, default=100)
    prep = commands.add_parser("prepare")
    prep.add_argument("--sample", type=Path, required=True)
    prep.add_argument("--candidate-id", required=True)
    prep.add_argument("--store", type=Path, default=Path("data/global_annotations"))
    prep.add_argument("--text-file", type=Path, required=True)
    prep.add_argument("--content-type", required=True)
    prep.add_argument("--rights-note", required=True)
    args = parser.parse_args()
    if args.command == "sample":
        config = {"schema_version": "aic-global-sampling-v1", "seed": args.seed, "per_stratum": args.per_stratum,
                  "publisher_cap": args.publisher_cap, "region_cap": args.region_cap, "max_total": args.max_total}
        result = sample_ranking(args.ranking, args.output, config)
    else:
        result = prepare_review(args.sample, args.candidate_id, args.store, args.text_file, args.content_type, args.rights_note)
    print(encoded(result).decode())


if __name__ == "__main__":
    main()
