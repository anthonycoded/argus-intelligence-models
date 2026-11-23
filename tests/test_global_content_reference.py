import pytest

from src.content_reference import (check_binding, load_source, prepare_discovery, register_source,
                                   validate_source_url)
from src.global_io import digest, encoded, read_object


def test_topic_independent_exact_reference(global_case):
    c = global_case
    ref, text, binding = load_source(c["root"], c["source"])
    assert text == c["text"]
    assert ref["canonical_source_id"] == "https://example.org/report"
    assert ref["content_revision_sha256"] == digest(c["text_file"].read_bytes())
    assert "topic" not in ref and "label" not in ref
    assert check_binding(c["root"], binding)[0] == ref
    prov = read_object(c["root"] / "sources" / c["source"] / "provenance.json")
    assert prov["rights_status"] == "unverified"


def test_duplicate_registration_retains_bytes(global_case):
    c = global_case
    path = c["root"] / "sources" / c["source"] / "reference.json"
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        register_source(c["root"], c["metadata"], c["text_file"])
    assert path.read_bytes() == before


def test_new_exact_revision_has_distinct_identity_same_duplicate_fingerprint(global_case):
    c = global_case
    first = load_source(c["root"], c["source"])[0]
    c["text_file"].write_bytes(c["text"].upper().encode("utf-8"))
    second_id = register_source(c["root"], c["metadata"], c["text_file"])
    second = load_source(c["root"], second_id)[0]
    assert second_id != c["source"]
    assert first["duplicate_fingerprint"] == second["duplicate_fingerprint"]
    assert first["canonical_source_id"] == second["canonical_source_id"]


@pytest.mark.parametrize("filename", ["content.utf8", "reference.json", "provenance.json"])
def test_missing_source_components_fail_closed(global_case, filename):
    c = global_case
    (c["root"] / "sources" / c["source"] / filename).unlink()
    with pytest.raises((ValueError, OSError)):
        load_source(c["root"], c["source"])


@pytest.mark.parametrize("filename", ["content.utf8", "reference.json", "provenance.json"])
def test_changed_source_components_fail_closed(global_case, filename):
    c = global_case
    path = c["root"] / "sources" / c["source"] / filename
    if filename == "content.utf8":
        path.write_bytes(path.read_bytes() + b"changed")
    else:
        obj = read_object(path)
        field = "canonical_source_id" if filename == "reference.json" else "rights_note"
        obj[field] = "changed"
        path.write_bytes(encoded(obj))
    with pytest.raises(ValueError):
        load_source(c["root"], c["source"])


def test_unknown_and_traversal_source_ids_rejected(global_case):
    c = global_case
    with pytest.raises(OSError):
        load_source(c["root"], "src-" + "0" * 64)
    with pytest.raises(ValueError):
        load_source(c["root"], "../../outside")


@pytest.mark.parametrize("url", ["http://example.org/a", "https://user:pass@example.org/a", "https://example.org:444/a",
                                 "https://example.org/a#fragment", "https://127.0.0.1/a", "https://[::1]/a",
                                 "https://localhost/a", "https://a.local/a", "https://example.org/\\evil",
                                 "https://example.org/\nsecret", "https://navy.mil.evil.test/x", "https://user@www.navy.mil/x"])
def test_strict_adapter_url_safety(url):
    with pytest.raises(ValueError):
        validate_source_url(url, "navy")


@pytest.mark.parametrize("field,value", [("collected_at", "2026-11-22"), ("published_at", "bad"),
                                        ("content_type", "metadata_only"), ("rights_note", ""), ("article_title", "")])
def test_invalid_registration_metadata_rejected(global_case, field, value):
    c = global_case
    metadata = {**c["metadata"], field: value}
    with pytest.raises(ValueError):
        register_source(c["root"], metadata, c["text_file"])


@pytest.mark.parametrize("adapter,host,publisher", [("navy", "www.navy.mil", "US Navy"),
                                                   ("defensenews", "www.defensenews.com", "Defense News")])
def test_both_discovery_adapters_prepare_with_provenance(global_case, tmp_path, adapter, host, publisher):
    c = global_case
    source_url = f"https://{host}/story"
    discovery_id = digest(source_url.encode())[:20]
    row = {"discovery_id": discovery_id, "source_id": source_url, "article_title": "Synthetic publisher report",
           "published_at_raw": "Fri, 20 Nov 2026 12:00:00 GMT", "collected_at": "2026-11-22T00:00:00Z",
           "review_status": "discovered_unreviewed"}
    if adapter == "defensenews":
        row["publisher"] = publisher
    discovery = tmp_path / "discovery.jsonl"
    discovery.write_bytes(encoded(row) + b"\n")
    ident = prepare_discovery(c["root"], discovery, discovery_id, adapter, c["text_file"], "human_summary", "Synthetic basis")
    ref, _, _ = load_source(c["root"], ident)
    assert ref["metadata"]["publisher"] == publisher
    prov = read_object(c["root"] / "sources" / ident / "provenance.json")
    assert prov["discovery"]["discovery_file_sha256"] == digest(discovery.read_bytes())
    assert prov["rights_status"] == "unverified"


@pytest.mark.parametrize("mutation", ["host", "publisher", "id", "status", "duplicate"])
def test_forged_or_ambiguous_discovery_rejected(global_case, tmp_path, mutation):
    c = global_case
    url = "https://www.defensenews.com/story"
    ident = digest(url.encode())[:20]
    row = {"discovery_id": ident, "source_id": url, "article_title": "Synthetic", "collected_at": "2026-11-22T00:00:00Z",
           "review_status": "discovered_unreviewed", "publisher": "Defense News"}
    if mutation == "host":
        row["source_id"] = "https://defensenews.com.evil.test/story"
    elif mutation == "publisher":
        row["publisher"] = "US Navy"
    elif mutation == "id":
        row["discovery_id"] = ident = "0" * 20
    elif mutation == "status":
        row["review_status"] = "approved"
    path = tmp_path / "bad-discovery.jsonl"
    path.write_bytes((encoded(row) + b"\n") * (2 if mutation == "duplicate" else 1))
    with pytest.raises(ValueError):
        prepare_discovery(c["root"], path, ident, "defensenews", c["text_file"], "human_summary", "basis")
