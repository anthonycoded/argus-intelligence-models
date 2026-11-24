"""Topic-independent immutable source revisions; registration never grants rights."""
import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

from .candidate_import import ALLOWED_TYPES, canonical_source, fingerprint
from .global_io import (digest, document_hash, encoded, hash_string, identifier, keys,
                        parse_json, publish_directory, read_object, string, timestamp)
from .government_sources import allowed_url
from .news_feeds import permitted_url

REPRESENTATIONS = ALLOWED_TYPES | {"reported_full_text", "ai_assisted_summary"}
METADATA_FIELDS = {"source_id", "publisher", "adapter", "article_title", "published_at",
                   "published_at_raw", "collected_at", "content_type", "rights_note", "provenance_method"}
REFERENCE_FIELDS = {"schema_version", "source_ref_id", "metadata", "canonical_source_id",
                    "content_revision_sha256", "duplicate_fingerprint", "provenance_id", "provenance_sha256"}
PROVENANCE_FIELDS = {"schema_version", "provenance_id", "canonical_source_id", "content_revision_sha256",
                     "metadata_sha256", "content_type", "rights_status", "rights_note", "method", "discovery"}


def validate_source_url(url, adapter):
    string(url, "source_id")
    if any(c.isspace() or ord(c) < 32 or c == "\\" for c in url):
        raise ValueError("Unsafe source URL")
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if (parts.scheme != "https" or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443) or parts.fragment or "." not in host
                or host.endswith((".local", ".localhost"))
                or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split("."))):
            raise ValueError("Unsafe source URL")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("IP-literal source URLs are unsupported")
        if adapter == "navy" and not allowed_url(url, roots=("navy.mil",)):
            raise ValueError("Navy publisher allowlist mismatch")
        if adapter == "defensenews" and not permitted_url(url):
            raise ValueError("Defense News publisher allowlist mismatch")
        if adapter not in {"manual", "navy", "defensenews"}:
            raise ValueError("Unknown source adapter")
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"Unsafe/unsupported source URL: {exc}") from exc


def validate_metadata(metadata):
    ai=isinstance(metadata,dict) and metadata.get('content_type')=='ai_assisted_summary'
    keys(metadata, METADATA_FIELDS | ({'representation_provenance'} if ai else set()), "content metadata")
    for field in METADATA_FIELDS - {"published_at", "published_at_raw"}:
        string(metadata[field], field)
    validate_source_url(metadata["source_id"], metadata["adapter"])
    expected = {"navy": "US Navy", "defensenews": "Defense News"}.get(metadata["adapter"])
    if expected and metadata["publisher"] != expected:
        raise ValueError("Publisher identity mismatch")
    timestamp(metadata["collected_at"], "collected_at")
    if metadata["published_at"] is not None:
        timestamp(metadata["published_at"], "published_at")
    if metadata["published_at_raw"] is not None:
        string(metadata["published_at_raw"], "published_at_raw")
    if metadata["content_type"] not in REPRESENTATIONS:
        raise ValueError("Unsupported content representation; metadata alone is not source content")
    if ai:
        from .representation_policy import validate_origin
        validate_origin(metadata['representation_provenance'],metadata['source_id'])
    return metadata


def _source_id(canonical, content_hash):
    return "src-" + document_hash([canonical, content_hash])


def _validate_discovery(proof, metadata):
    if proof is None:
        return
    keys(proof, {"adapter", "discovery_file_sha256", "discovery_id", "discovery_row_sha256"}, "discovery provenance")
    if (metadata["adapter"] not in {"navy", "defensenews"} or proof["adapter"] != metadata["adapter"]
            or proof["discovery_id"] != digest(canonical_source(metadata["source_id"]).encode())[:20]
            or metadata["provenance_method"] != "human_supplied_content_from_discovery"):
        raise ValueError("Discovery provenance identity mismatch")
    for key in ("discovery_file_sha256", "discovery_row_sha256"):
        hash_string(proof[key], key)


def register_source(root, metadata, text_file, discovery=None):
    validate_metadata(metadata)
    _validate_discovery(discovery, metadata)
    raw = Path(text_file).read_bytes()
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise ValueError("Content must be nonempty and at most 2 MiB")
    text = raw.decode("utf-8")
    if not text.strip("\ufeff \r\n\t"):
        raise ValueError("Empty source content")
    canonical, revision = canonical_source(metadata["source_id"]), digest(raw)
    ai=metadata['content_type']=='ai_assisted_summary'
    if ai:
        from .representation_policy import check_original
        check_original(root,metadata)
    ident = _source_id(canonical, revision)
    prov = {"schema_version": "aic-global-provenance-v2" if ai else "aic-global-provenance-v1", "canonical_source_id": canonical,
            "content_revision_sha256": revision, "metadata_sha256": document_hash(metadata),
            "content_type": metadata["content_type"], "rights_status": "unverified",
            "rights_note": metadata["rights_note"], "method": metadata["provenance_method"], "discovery": discovery}
    prov["provenance_id"] = "prov-" + document_hash(prov)
    reference = {"schema_version": "aic-content-reference-v2" if ai else "aic-content-reference-v1", "source_ref_id": ident, "metadata": metadata,
                 "canonical_source_id": canonical, "content_revision_sha256": revision,
                 "duplicate_fingerprint": fingerprint(text), "provenance_id": prov["provenance_id"],
                 "provenance_sha256": digest(encoded(prov))}
    publish_directory(Path(root) / "sources" / ident,
                      {"reference.json": encoded(reference), "provenance.json": encoded(prov), "content.utf8": raw})
    return ident


def load_source(root, ident, *, _ancestors=None):
    identifier(ident, "src-")
    ancestors=set(_ancestors or ())
    if ident in ancestors or len(ancestors)>=32:raise ValueError('Cyclic or excessive original representation ancestry')
    ancestors.add(ident)
    directory = Path(root) / "sources" / ident
    ref = read_object(directory / "reference.json")
    keys(ref, REFERENCE_FIELDS, "content reference")
    validate_metadata(ref["metadata"])
    ai=ref['metadata']['content_type']=='ai_assisted_summary'
    if ai:
        from .representation_policy import check_original
        check_original(root,ref['metadata'],ancestors)
    raw = (directory / "content.utf8").read_bytes()
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise ValueError("Invalid stored content size")
    text = raw.decode("utf-8")
    canonical = canonical_source(ref["metadata"]["source_id"])
    prov = read_object(directory / "provenance.json")
    keys(prov, PROVENANCE_FIELDS, "global provenance")
    _validate_discovery(prov["discovery"], ref["metadata"])
    prov_body = {k: v for k, v in prov.items() if k != "provenance_id"}
    if (ref["schema_version"] != ("aic-content-reference-v2" if ai else "aic-content-reference-v1") or ref["source_ref_id"] != ident
            or ref["canonical_source_id"] != canonical or ref["content_revision_sha256"] != digest(raw)
            or ident != _source_id(canonical, digest(raw)) or ref["duplicate_fingerprint"] != fingerprint(text)
            or prov["schema_version"] != ("aic-global-provenance-v2" if ai else "aic-global-provenance-v1") or prov["rights_status"] != "unverified"
            or prov["canonical_source_id"] != canonical or prov["content_revision_sha256"] != digest(raw)
            or prov["metadata_sha256"] != document_hash(ref["metadata"])
            or prov["content_type"] != ref["metadata"]["content_type"]
            or prov["rights_note"] != ref["metadata"]["rights_note"] or prov["method"] != ref["metadata"]["provenance_method"]
            or prov["provenance_id"] != "prov-" + document_hash(prov_body)
            or ref["provenance_id"] != prov["provenance_id"]
            or ref["provenance_sha256"] != digest((directory / "provenance.json").read_bytes())):
        raise ValueError("Stale/mismatched source content or provenance identity")
    binding = {"source_ref_id": ident, "reference_sha256": digest((directory / "reference.json").read_bytes()),
               "content_revision_sha256": ref["content_revision_sha256"], "provenance_sha256": ref["provenance_sha256"]}
    return ref, text, binding


def check_binding(root, binding):
    keys(binding, {"source_ref_id", "reference_sha256", "content_revision_sha256", "provenance_sha256"}, "content binding")
    for key in ("reference_sha256", "content_revision_sha256", "provenance_sha256"):
        hash_string(binding[key], key)
    ref, text, actual = load_source(root, binding["source_ref_id"])
    if binding != actual:
        raise ValueError("Stale content reference binding")
    return ref, text


def prepare_discovery(root, discovery_file, discovery_id, adapter, text_file, content_type, rights_note):
    """Offline, allowlisted bridge for BOTH collectors; never fetches article bodies."""
    if adapter not in {"navy", "defensenews"}:
        raise ValueError("Preparation requires a known publisher adapter")
    raw = Path(discovery_file).read_bytes()
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("Discovery input too large")
    matches = []
    for line in raw.decode("utf-8-sig").splitlines():
        if not line.strip():
            continue
        row = parse_json(line)
        if not isinstance(row, dict):
            raise ValueError("Invalid discovery row")
        if row.get("discovery_id") == discovery_id:
            matches.append(row)
    if len(matches) != 1:
        raise ValueError("Discovery ID must identify exactly one row")
    row = matches[0]
    validate_source_url(row.get("source_id"), adapter)
    canonical = canonical_source(row["source_id"])
    if row.get("review_status") != "discovered_unreviewed" or discovery_id != digest(canonical.encode())[:20]:
        raise ValueError("Discovery identity/status mismatch")
    if adapter == "defensenews" and row.get("publisher") != "Defense News":
        raise ValueError("Discovery publisher mismatch")
    metadata = {"source_id": row["source_id"], "adapter": adapter,
                "publisher": {"navy": "US Navy", "defensenews": "Defense News"}[adapter],
                "article_title": row.get("article_title"), "published_at": None,
                "published_at_raw": row.get("published_at_raw"), "collected_at": row.get("collected_at"),
                "content_type": content_type, "rights_note": rights_note,
                "provenance_method": "human_supplied_content_from_discovery"}
    proof = {"adapter": adapter, "discovery_file_sha256": digest(raw),
             "discovery_id": discovery_id, "discovery_row_sha256": document_hash(row)}
    return register_source(root, metadata, text_file, discovery=proof)
