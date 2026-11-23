"""Versioned, multi-query local discovery. Similarity is never a truth label."""
import argparse
import hashlib
import importlib.metadata
import re
from pathlib import Path

from .content_reference import load_source, validate_source_url
from .global_io import digest, document_hash, encoded, keys, parse_json, publish_directory, read_object, string
from .global_taxonomy import load_taxonomy
from .global_feeds import REGIONS
from .semantic_ranker import DEFAULT_MODEL, _atomic_new, _unit, _valid_vector, read_discoveries, topic_query
from .topic_spec import read_topic_spec

DEFAULT_PROFILE = Path(__file__).resolve().parents[1] / "profiles/global_intelligence_v1.json"
TAXONOMY = Path(__file__).resolve().parents[1] / "taxonomies/global_intelligence_v2.json"
DISCOVERY_FIELDS = {"source_id", "discovery_id", "article_title", "published_at_raw", "published_at", "updated_at_raw", "collected_at", "publisher",
                    "publisher_country", "source_region", "language", "feed_id", "content_type", "review_status",
                    "metadata_basis", "priority", "matched_terms", "selected_for_review", "discovered_from_file", "source_ref_id"}


def validate_profile(profile):
    keys(profile, {"profile_id", "version", "taxonomy_sha256", "language_support", "queries", "scoring"}, "query profile")
    string(profile["profile_id"], "profile_id")
    string(profile["version"], "profile version")
    tax = load_taxonomy(TAXONOMY)
    if profile["taxonomy_sha256"] != document_hash(tax):
        raise ValueError("Profile taxonomy hash mismatch")
    languages = profile["language_support"]
    if not isinstance(languages, list) or not languages or any(not isinstance(v, str) or not re.fullmatch(r"[a-z]{2,3}", v) for v in languages):
        raise ValueError("Explicit profile language support required")
    if not isinstance(profile["queries"], list) or not 1 <= len(profile["queries"]) <= 128:
        raise ValueError("Profile needs 1-128 explicit queries")
    seen = set()
    for query in profile["queries"]:
        keys(query, {"id", "domain", "event_type", "text", "keywords", "language"}, "query")
        for key in ("id", "text"):
            string(query[key], key)
        if len(query["text"]) > 4000 or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", query["id"]) or query["id"] in seen:
            raise ValueError("Duplicate query ID or oversized query")
        seen.add(query["id"])
        if query["domain"] not in tax["domains"] or query["domain"] == "other" or query["language"] not in languages:
            raise ValueError("Unsupported query domain/language")
        if query["event_type"] is not None and (query["domain"] != "defense" or query["event_type"] not in tax["defense_event_types"]):
            raise ValueError("Unknown defense event query")
        if not isinstance(query["keywords"], list) or any(not isinstance(k, str) or not k.strip() for k in query["keywords"]):
            raise ValueError("Invalid keyword query")
    keys(profile["scoring"], {"aggregation", "hybrid_semantic_weight", "max_sequence_length"}, "scoring")
    config = profile["scoring"]
    if (config["aggregation"] != "max_cosine" or type(config["hybrid_semantic_weight"]) not in (int, float)
            or not 0 <= config["hybrid_semantic_weight"] <= 1
            or type(config["max_sequence_length"]) is not int or not 16 <= config["max_sequence_length"] <= 512):
        raise ValueError("Unsupported scoring configuration")
    return profile


def _embedding_identity(model, revision, profile, encoder_id):
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
        raise ValueError("An immutable model revision (40/64 hex characters) is required; main/latest are refused")
    string(model, "model")
    if Path(model).is_dir() and revision != model_directory_hash(model):
        raise ValueError("Local model directory does not match its declared immutable revision fingerprint")
    versions = {}
    for package in ("sentence-transformers", "transformers", "torch"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not_installed"
    return {"model": model, "revision": revision, "backend": encoder_id or "sentence-transformers-local",
            "packages": versions, "profile_sha256": document_hash(profile), "device": "cpu",
            "max_sequence_length": profile["scoring"]["max_sequence_length"], "normalize": True}


def model_directory_hash(directory):
    files = []
    for path in sorted(Path(directory).rglob("*")):
        if path.is_file():
            hasher = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(block)
            files.append([path.relative_to(directory).as_posix(), hasher.hexdigest()])
    if not files:
        raise ValueError("Empty local model directory")
    return document_hash(files)


def _valid_global_vector(vector):
    return (isinstance(vector, list) and all(isinstance(v, (int, float)) and abs(v) <= 1e6 for v in vector)
            and _valid_vector(vector))


def _vectors(items, identity, cache_dir, encoder):
    results, pending = [None] * len(items), {}
    for i, (text, revision) in enumerate(items):
        binding = {"identity": identity, "input_revision": revision, "text_sha256": digest(text.encode())}
        key = document_hash(binding)
        path = Path(cache_dir) / f"{key}.json"
        if path.exists():
            cached = read_object(path)
            keys(cached, {"binding", "vector"}, "embedding cache")
            if cached["binding"] != binding or not _valid_global_vector(cached["vector"]):
                raise ValueError("Stale/corrupt revision-bound embedding cache")
            results[i] = _unit(cached["vector"])
        else:
            pending.setdefault(key, {"text": text, "binding": binding, "indices": []})["indices"].append(i)
    if pending:
        if encoder is None:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(identity["model"], revision=identity["revision"], device="cpu",
                                        local_files_only=True, trust_remote_code=False)
            model.max_seq_length = identity["max_sequence_length"]
            encoder = lambda texts: model.encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        vectors = encoder([p["text"] for p in pending.values()])
        if len(vectors) != len(pending):
            raise ValueError("Encoder count mismatch")
        for (key, item), vector in zip(pending.items(), vectors):
            vector = vector.tolist() if hasattr(vector, "tolist") else list(vector)
            if not _valid_global_vector(vector):
                raise ValueError("Invalid embedding vector")
            vector = _unit(vector)
            for i in item["indices"]:
                results[i] = vector
            _atomic_new(Path(cache_dir) / f"{key}.json", encoded({"binding": item["binding"], "vector": vector}))
    if len({len(v) for v in results}) != 1:
        raise ValueError("Inconsistent embedding dimensions")
    return results


def rank_global(inputs, output, cache_dir, model=DEFAULT_MODEL, revision=None, profile=DEFAULT_PROFILE,
                store=None, encoder=None, encoder_id=None, topic=None):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    if encoder is not None and not encoder_id:
        raise ValueError("Injected encoders require an explicit encoder_id; test and production caches must be distinct")
    profile = read_object(profile) if isinstance(profile, (str, Path)) else profile
    validate_profile(profile)
    if topic is not None:
        spec = read_topic_spec(topic)
        profile = {**profile, "profile_id": spec["topic_id"], "version": spec["policy_version"],
                   "queries": [{"id": "explicit-topic", "domain": "defense", "event_type": None,
                                "language": "en", "text": topic_query(spec), "keywords": []}],
                   "topic_policy": spec}
    identity = _embedding_identity(model, revision, profile, encoder_id)
    records, stats = read_discoveries([Path(p) for p in inputs])
    if not 1 <= len(records) <= 1000 or len(inputs) > 100:
        raise ValueError("Global pilot ranking requires 1-1000 usable records and at most 100 input files")
    queries = profile["queries"]
    items = [(q["text"], document_hash(q)) for q in queries]
    prepared = []
    for row in records:
        # Do not carry unlicensed bodies/descriptions, labels, credentials or other
        # arbitrary input fields into a discovery output. Input file hashes retain provenance.
        row = {k: v for k, v in row.items() if k in DISCOVERY_FIELDS}
        validate_source_url(row["source_id"], "manual")
        if row.get("publisher") is not None:
            string(row["publisher"], "publisher metadata")
        if row.get("source_region", "unknown") not in REGIONS:
            raise ValueError("Invalid configured source region")
        if row.get("language") is not None and (not isinstance(row["language"], str) or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]+)*", row["language"])):
            raise ValueError("Invalid language metadata")
        title = row["article_title"].strip()
        source_binding = None
        body_hash = None
        if row.get("source_ref_id"):
            if store is None:
                raise ValueError("Registered content requires its Phase 2M store")
            ref, body, source_binding = load_source(store, row["source_ref_id"])
            if ref["canonical_source_id"] != row["source_id"]:
                raise ValueError("Discovery/source reference identity mismatch")
            title = ref["metadata"]["article_title"]
            row = {**row, "article_title": title, "publisher": ref["metadata"]["publisher"]}
            text, basis = title + "\n" + body, "registered_content"
            body_hash = ref["content_revision_sha256"]
        else:
            text, basis = title, "title_only"
        revision_binding = {"basis": basis, "content_revision_sha256": body_hash,
                            "ranking_text_sha256": digest(text.encode()), "source_binding": source_binding}
        items.append((text, document_hash(revision_binding)))
        prepared.append((row, text, revision_binding))
    vectors = _vectors(items, identity, cache_dir, encoder)
    results = []
    for (row, text, article_revision), vector in zip(prepared, vectors[len(queries):]):
        scores, domains, events, matches = {}, {}, {}, set()
        for query, qvector in zip(queries, vectors):
            score = round(max(-1., min(1., sum(a * b for a, b in zip(vector, qvector)))), 6)
            scores[query["id"]] = score
            domains[query["domain"]] = max(domains.get(query["domain"], -1.), score)
            if query["event_type"]:
                events[query["event_type"]] = max(events.get(query["event_type"], -1.), score)
            matches.update(k for k in query["keywords"] if re.search(r"(?<!\w)" + re.escape(k.casefold()) + r"(?!\w)", text.casefold()))
        best = max(queries, key=lambda q: scores[q["id"]])
        semantic, keyword = max(scores.values()), min(1., len(matches) / 3)
        alpha = profile["scoring"]["hybrid_semantic_weight"]
        ranking = {"profile_id": profile["profile_id"], "profile_version": profile["version"],
                   "profile_sha256": document_hash(profile), "model": identity, "scoring": profile["scoring"],
                   "article_revision": article_revision, "query_scores": scores, "domain_scores": domains,
                   "event_type_scores": events, "semantic_score": semantic, "keyword_score": keyword,
                   "hybrid_score": round(alpha * (semantic + 1) / 2 + (1 - alpha) * keyword, 6),
                   "matched_keywords": sorted(matches), "query_hint": best["event_type"] or best["domain"],
                   "hint_is_ground_truth": False, "scores_are_confidence": False,
                   "language_status": "unknown" if not row.get("language") else "declared_supported" if row["language"].split("-")[0] in profile["language_support"] else "unsupported_unvalidated"}
        candidate_id = "candidate-" + document_hash([row["source_id"], article_revision])
        results.append({**row, "candidate_id": candidate_id, "ranking": ranking})
    results.sort(key=lambda r: (-r["ranking"]["semantic_score"], r["source_id"]))
    payload = b"".join(encoded(r) + b"\n" for r in results)
    if len(payload) > 128 * 1024 * 1024:
        raise ValueError("Ranking bundle exceeds 128 MiB pilot limit")
    manifest = {"schema_version": "aic-global-ranking-v1", "mode": "topic" if topic else "global",
                "profile": profile, "model": identity, "inputs": [{"path": str(p), "sha256": digest(Path(p).read_bytes())} for p in inputs],
                "records": len(results), "statistics": stats, "ranking_sha256": digest(payload)}
    publish_directory(output, {"ranking.jsonl": payload, "manifest.json": encoded(manifest)})
    return manifest


def load_ranking(directory):
    directory = Path(directory)
    manifest = read_object(directory / "manifest.json")
    keys(manifest, {"schema_version", "mode", "profile", "model", "inputs", "records", "statistics", "ranking_sha256"}, "ranking manifest")
    if manifest.get("schema_version") != "aic-global-ranking-v1" or manifest["mode"] not in {"global", "topic"}:
        raise ValueError("Unsupported ranking manifest")
    if manifest["mode"] == "global":
        validate_profile(manifest["profile"])
    elif "topic_policy" not in manifest["profile"]:
        raise ValueError("Topic ranking needs an explicit pinned policy")
    if manifest["model"]["profile_sha256"] != document_hash(manifest["profile"]):
        raise ValueError("Model/profile cache identity mismatch")
    raw = (directory / "ranking.jsonl").read_bytes()
    if len(raw) > 128 * 1024 * 1024 or digest(raw) != manifest["ranking_sha256"]:
        raise ValueError("Ranking hash/size mismatch")
    rows = [parse_json(line) for line in raw.decode().splitlines() if line.strip()]
    if len(rows) != manifest["records"] or len({r["candidate_id"] for r in rows}) != len(rows):
        raise ValueError("Ranking membership mismatch")
    for row in rows:
        meta = row["ranking"]
        if (meta["profile_sha256"] != document_hash(manifest["profile"]) or meta["model"] != manifest["model"]
                or set(meta["query_scores"]) != {q["id"] for q in manifest["profile"]["queries"]}
                or row["candidate_id"] != "candidate-" + document_hash([row["source_id"], meta["article_revision"]])
                or meta["scoring"] != manifest["profile"]["scoring"]
                or meta["profile_id"] != manifest["profile"]["profile_id"] or meta["profile_version"] != manifest["profile"]["version"]
                or meta["hint_is_ground_truth"] is not False or meta["scores_are_confidence"] is not False):
            raise ValueError("Ranking identity/profile mismatch")
        scores = meta["query_scores"]
        if any(type(v) not in (float, int) or not -1 <= v <= 1 for v in scores.values()) or meta["semantic_score"] != max(scores.values()):
            raise ValueError("Invalid semantic ranking scores")
        keyword = min(1., len(set(meta["matched_keywords"])) / 3)
        alpha = meta["scoring"]["hybrid_semantic_weight"]
        if meta["keyword_score"] != keyword or meta["hybrid_score"] != round(alpha * (meta["semantic_score"] + 1) / 2 + (1 - alpha) * keyword, 6):
            raise ValueError("Invalid keyword/hybrid scoring configuration")
        if meta["article_revision"]["basis"] == "title_only" and meta["article_revision"]["ranking_text_sha256"] != digest(row["article_title"].strip().encode()):
            raise ValueError("Ranking title revision mismatch")
    return manifest, rows


def main():
    parser = argparse.ArgumentParser(description="Global multi-query discovery; local cached models only; no automatic labels")
    parser.add_argument("--inputs", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New output bundle directory")
    parser.add_argument("--cache-dir", type=Path, default=Path("data/embedding_cache/global-v1"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--mode", choices=("global", "topic"), default="global")
    parser.add_argument("--topic", type=Path)
    parser.add_argument("--store", type=Path)
    args = parser.parse_args()
    if (args.mode == "topic") != (args.topic is not None):
        parser.error("--mode topic requires an explicit --topic; global mode forbids it")
    result = rank_global(args.inputs, args.output, args.cache_dir, args.model, args.model_revision,
                         args.profile, args.store, topic=args.topic)
    print(encoded({"records": result["records"], "mode": result["mode"]}).decode())


if __name__ == "__main__":
    main()
