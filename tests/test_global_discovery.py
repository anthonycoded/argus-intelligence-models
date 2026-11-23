from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.global_discovery import (DEFAULT_PROFILE, load_ranking, model_directory_hash, rank_global, validate_profile)
from src.global_io import encoded, read_object
from src.semantic_ranker import read_discoveries


def fake_encoder(texts):
    return [[1., 0., 0.] if "military" in t.lower() or "exercise" in t.lower() else [0., 1., 0.] for t in texts]


def write_discoveries(tmp_path, rows=None):
    path = tmp_path / "discoveries.jsonl"
    rows = rows or [{"source_id": "https://example.org/exercise", "article_title": "Military exercise in Kenya",
                     "publisher": "Synthetic Kenya publisher", "source_region": "Africa", "language": "en",
                     "collected_at": "2026-11-22T00:00:00Z"},
                    {"source_id": "https://example.org/economy", "article_title": "Economic policy in Brazil",
                     "publisher": "Synthetic Brazil publisher", "source_region": "South America", "language": "pt",
                     "collected_at": "2026-11-22T00:00:00Z"}]
    path.write_bytes(b"".join(encoded(r) + b"\n" for r in rows))
    return path


def rank_fixture(tmp_path, output="ranked", **kwargs):
    inputs = kwargs.pop("inputs", None)
    if inputs is None:
        inputs = [write_discoveries(tmp_path)]
    return rank_global(inputs, tmp_path / output, tmp_path / "cache", revision="a" * 40,
                       encoder=fake_encoder, encoder_id="synthetic-v1", **kwargs)


def test_default_global_queries_cover_all_domains_and_events():
    profile = validate_profile(read_object(DEFAULT_PROFILE))
    assert {q["domain"] for q in profile["queries"]} == {"defense", "economics", "geopolitics", "cybersecurity"}
    assert all(sum(q["event_type"] == event for q in profile["queries"]) >= 2 for event in
               {q["event_type"] for q in profile["queries"] if q["event_type"]})
    assert "taiwan" not in json.dumps(profile).lower() and "china" not in json.dumps(profile).lower()


def test_titleless_duplicates_do_not_hide_usable_titles_and_urls_are_canonical(tmp_path):
    path = write_discoveries(tmp_path, [{"source_id": "https://EXAMPLE.org/a/?utm_source=x", "article_title": ""},
                                       {"source_id": "https://example.org/a", "article_title": "Actual title"},
                                       {"source_id": "https://example.org/a/?utm_campaign=y", "article_title": "Duplicate"}])
    rows, stats = read_discoveries([path])
    assert len(rows) == 1 and rows[0]["source_id"] == "https://example.org/a"
    assert stats["missing_title"] == 1 and stats["duplicates"] == 1


def test_ranking_metadata_is_revision_bound_and_not_truth(tmp_path):
    rank_fixture(tmp_path)
    manifest, rows = load_ranking(tmp_path / "ranked")
    assert manifest["mode"] == "global"
    meta = rows[0]["ranking"]
    assert meta["model"]["revision"] == "a" * 40
    assert len(meta["profile_sha256"]) == 64 and len(meta["query_scores"]) == 26
    assert not meta["scores_are_confidence"] and not meta["hint_is_ground_truth"]
    assert meta["article_revision"]["basis"] == "title_only"
    assert meta["article_revision"]["content_revision_sha256"] is None


def test_cache_hits_need_no_encoder_and_identity_changes_do_not_reuse_cache(tmp_path):
    path = write_discoveries(tmp_path)
    rank_fixture(tmp_path, inputs=[path])
    def fail(_):
        pytest.fail("Cache hit reran encoder")
    rank_global([path], tmp_path / "again", tmp_path / "cache", revision="a" * 40, encoder=fail, encoder_id="synthetic-v1")
    calls = []
    def counted(texts):
        calls.extend(texts)
        return fake_encoder(texts)
    rank_global([path], tmp_path / "new-revision", tmp_path / "cache", revision="b" * 40, encoder=counted, encoder_id="synthetic-v1")
    assert calls


@pytest.mark.parametrize("change", ["version", "query", "scoring"])
def test_profile_cache_identity_changes(tmp_path, change):
    path = write_discoveries(tmp_path)
    rank_fixture(tmp_path, inputs=[path])
    profile = read_object(DEFAULT_PROFILE)
    if change == "version":
        profile["version"] = "test-profile-v2"
    elif change == "query":
        profile["queries"][0]["text"] += " Updated research query."
    else:
        profile["scoring"]["max_sequence_length"] = 128
    calls = []
    def counted(texts):
        calls.extend(texts)
        return fake_encoder(texts)
    rank_global([path], tmp_path / "changed", tmp_path / "cache", revision="a" * 40,
                profile=profile, encoder=counted, encoder_id="synthetic-v1")
    assert calls


def test_changed_title_invalidates_embedding(tmp_path):
    path = write_discoveries(tmp_path)
    rank_fixture(tmp_path, inputs=[path])
    rows, _ = read_discoveries([path])
    rows[0]["article_title"] = "Changed source title revision"
    write_discoveries(tmp_path, rows)
    calls = []
    def counted(texts):
        calls.extend(texts)
        return fake_encoder(texts)
    rank_global([path], tmp_path / "changed", tmp_path / "cache", revision="a" * 40, encoder=counted, encoder_id="synthetic-v1")
    assert calls == ["Changed source title revision"]


def test_registered_content_binding_and_stale_content_rejection(global_case, tmp_path):
    c = global_case
    path = write_discoveries(tmp_path, [{"source_id": c["metadata"]["source_id"], "source_ref_id": c["source"],
                                       "article_title": "Old title"}])
    rank_fixture(tmp_path, inputs=[path], store=c["root"])
    _, rows = load_ranking(tmp_path / "ranked")
    assert rows[0]["ranking"]["article_revision"]["content_revision_sha256"]
    (c["root"] / "sources" / c["source"] / "content.utf8").write_bytes(b"Changed")
    with pytest.raises(ValueError):
        rank_fixture(tmp_path, output="stale", inputs=[path], store=c["root"])


def test_corrupt_cache_is_rejected(tmp_path):
    rank_fixture(tmp_path)
    path = next((tmp_path / "cache").glob("*.json"))
    obj = read_object(path)
    obj["binding"]["identity"]["revision"] = "wrong"
    path.write_bytes(encoded(obj))
    with pytest.raises(ValueError, match="cache"):
        rank_fixture(tmp_path, output="corrupt")


@pytest.mark.parametrize("revision", [None, "main", "latest", "abc"])
def test_unpinned_model_rejected_before_import(tmp_path, revision):
    with pytest.raises(ValueError, match="immutable model revision"):
        rank_global([write_discoveries(tmp_path)], tmp_path / "output", tmp_path / "cache", revision=revision)


def test_local_model_fingerprint_is_verified_without_loading(tmp_path):
    directory = tmp_path / "model"
    directory.mkdir()
    (directory / "config.json").write_bytes(b"synthetic model fingerprint fixture")
    revision = model_directory_hash(directory)
    path = write_discoveries(tmp_path)
    rank_global([path], tmp_path / "good", tmp_path / "cache", model=str(directory), revision=revision,
                encoder=fake_encoder, encoder_id="synthetic-v1")
    (directory / "config.json").write_bytes(b"changed")
    with pytest.raises(ValueError, match="fingerprint"):
        rank_global([path], tmp_path / "bad", tmp_path / "cache", model=str(directory), revision=revision,
                    encoder=fake_encoder, encoder_id="synthetic-v1")


def test_topic_mode_is_explicit_and_outputs_are_not_overwritten(tmp_path):
    rank_fixture(tmp_path, topic=Path("topics/taiwan_military_v2.json"))
    assert load_ranking(tmp_path / "ranked")[0]["mode"] == "topic"
    with pytest.raises(FileExistsError):
        rank_fixture(tmp_path)


def test_duplicate_query_ids_rejected():
    profile = read_object(DEFAULT_PROFILE)
    profile["queries"].append(deepcopy(profile["queries"][0]))
    with pytest.raises(ValueError, match="Duplicate query"):
        validate_profile(profile)


def test_ranking_manifest_tampering_cannot_change_profile_identity(tmp_path):
    rank_fixture(tmp_path)
    path = tmp_path / "ranked/manifest.json"
    obj = read_object(path)
    obj["profile"]["version"] = "silently-changed-version"
    path.write_bytes(encoded(obj))
    with pytest.raises(ValueError, match="identity"):
        load_ranking(tmp_path / "ranked")


def test_unlicensed_body_and_arbitrary_fields_are_not_copied(tmp_path):
    path = write_discoveries(tmp_path, [{"source_id": "https://example.org/report", "article_title": "Allowed metadata",
                                       "article_text": "DO NOT COPY UNLICENSED BODY", "description": "DO NOT COPY", "api_key": "synthetic-secret"}])
    rank_fixture(tmp_path, inputs=[path])
    raw = (tmp_path / "ranked/ranking.jsonl").read_text()
    assert "DO NOT COPY" not in raw and "synthetic-secret" not in raw and "article_text" not in raw
