"""Phase 2K: global multi-domain event annotations, independent of topic relevance.

Only the defense event family is fully enumerated in v1. No LLM labels are
silently promoted to human ground truth. Existing pilot.jsonl is untouched.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_TAXONOMY = {"taxonomy_id", "version", "description", "domains", "defense_event_types", "entity_roles", "annotation_statuses", "evidence_statuses", "guidance"}
REQUIRED_ANNOTATION = {"record_id", "source_id", "event_group_id", "taxonomy_version", "annotation_status", "reviewed_by", "domains", "defense_event_types", "countries", "organizations", "event_location", "event_date", "evidence_status", "evidence", "rationale"}
COUNTRY_ROLES = {"actor", "target", "host", "participant", "affected", "mentioned"}


def _string(value: Any, name: str, allow_null: bool = False) -> None:
    if value is None and allow_null:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string" + (" or null" if allow_null else ""))


def _unique_names(value: Any, choices: set[str], name: str, allow_empty: bool = False) -> None:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError(f"{name} must be a {'possibly empty ' if allow_empty else ''}list")
    if len(value) != len(set(map(str, value))) or any(not isinstance(v, str) or v not in choices for v in value):
        raise ValueError(f"{name} contains duplicates or unknown values")


def validate_taxonomy(obj: Any) -> dict:
    if not isinstance(obj, dict) or set(obj) != REQUIRED_TAXONOMY:
        raise ValueError("taxonomy has missing or unexpected keys")
    for key in ("taxonomy_id", "version", "description"):
        _string(obj[key], key)
    if not re.fullmatch(r"aic-global-v\d+", obj["version"]):
        raise ValueError("taxonomy version must be aic-global-vN")
    for key in ("domains", "defense_event_types", "entity_roles", "annotation_statuses", "evidence_statuses"):
        values = obj[key]
        if not isinstance(values, list) or not values or any(not isinstance(x, str) or not x.strip() for x in values) or len(values) != len(set(values)):
            raise ValueError(f"{key} must contain unique nonempty strings")
    if "defense" not in obj["domains"] or "other" not in obj["domains"]:
        raise ValueError("taxonomy must include defense and other")
    if not COUNTRY_ROLES.issubset(set(obj["entity_roles"])):
        raise ValueError("entity roles missing")
    if not {"pending", "human_verified"}.issubset(set(obj["annotation_statuses"])):
        raise ValueError("annotation statuses missing")
    if not isinstance(obj["guidance"], dict) or not set(obj["domains"]).issubset(obj["guidance"]) or not {"multi_label", "no_inference"}.issubset(obj["guidance"]):
        raise ValueError("guidance incomplete")
    if any(not isinstance(x, str) or not x.strip() for x in obj["guidance"].values()):
        raise ValueError("guidance must contain nonempty explanations")
    return obj


def load_taxonomy(path: str | Path) -> dict:
    return validate_taxonomy(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def validate_global_annotation(row: Any, taxonomy: dict) -> dict:
    validate_taxonomy(taxonomy)
    if not isinstance(row, dict) or set(row) != REQUIRED_ANNOTATION:
        raise ValueError(f"annotation keys missing={sorted(REQUIRED_ANNOTATION-set(row)) if isinstance(row,dict) else 'invalid'}; extra={sorted(set(row)-REQUIRED_ANNOTATION) if isinstance(row,dict) else 'invalid'}")
    for key in ("record_id", "source_id", "event_group_id", "taxonomy_version", "annotation_status", "evidence_status", "rationale"):
        _string(row[key], key)
    if row["taxonomy_version"] != taxonomy["version"]:
        raise ValueError("taxonomy version mismatch")
    if row["annotation_status"] not in taxonomy["annotation_statuses"]:
        raise ValueError("unknown annotation status")
    _string(row["reviewed_by"], "reviewed_by", allow_null=True)
    if row["annotation_status"] == "human_verified" and row["reviewed_by"] is None:
        raise ValueError("human_verified requires reviewed_by")
    if row["annotation_status"] == "pending" and row["reviewed_by"] is not None:
        raise ValueError("pending must not claim a reviewer")
    if row["evidence_status"] not in taxonomy["evidence_statuses"]:
        raise ValueError("unknown evidence status")
    _unique_names(row["domains"], set(taxonomy["domains"]), "domains")
    if "other" in row["domains"] and len(row["domains"]) > 1:
        raise ValueError("other cannot coexist with intelligence domains")
    _unique_names(row["defense_event_types"], set(taxonomy["defense_event_types"]), "defense_event_types", allow_empty=True)
    if row["defense_event_types"] and "defense" not in row["domains"]:
        raise ValueError("defense event types require defense domain")
    if row["annotation_status"] == "human_verified" and "defense" in row["domains"] and not row["defense_event_types"]:
        raise ValueError("verified defense annotations require at least one defense event type")
    if not isinstance(row["countries"], list) or not isinstance(row["organizations"], list):
        raise ValueError("countries and organizations must be lists")
    for country in row["countries"]:
        if not isinstance(country, dict) or set(country) != {"code", "role"}:
            raise ValueError("countries need code and role")
        if not isinstance(country["code"], str) or not re.fullmatch(r"[A-Z]{2}", country["code"]):
            raise ValueError("country code must be ISO-3166-style alpha-2 (membership not checked)")
        if country["role"] not in taxonomy["entity_roles"]:
            raise ValueError("unknown country role")
    if len(row["countries"]) != len({(x["code"],x["role"]) for x in row["countries"]}):
        raise ValueError("duplicate country roles")
    if any(not isinstance(s, str) or not s.strip() for s in row["organizations"]):
        raise ValueError("organizations must be nonempty strings")
    if len(row["organizations"]) != len(set(row["organizations"])):
        raise ValueError("duplicate organizations")
    _string(row["event_location"], "event_location", allow_null=True)
    _string(row["event_date"], "event_date", allow_null=True)
    if row["event_date"] is not None:
        try:
            datetime.strptime(row["event_date"], "%Y-%m-%d")
        except ValueError as e:
            raise ValueError("event_date must be YYYY-MM-DD or null") from e
    if not isinstance(row["evidence"], list) or (row["annotation_status"] == "human_verified" and not row["evidence"]):
        raise ValueError("evidence must be a list, nonempty when verified")
    for item in row["evidence"]:
        if not isinstance(item, dict) or set(item) != {"field", "text"}:
            raise ValueError("evidence items require field and text")
        _string(item["field"], "evidence.field")
        _string(item["text"], "evidence.text")
    return row


def validate_jsonl(path: str | Path, taxonomy: dict) -> dict:
    seen = set()
    counts: dict[str,int] = {}
    total = 0
    for line_num, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            validate_global_annotation(row, taxonomy)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Line {line_num}: {exc}") from exc
        if row["record_id"] in seen:
            raise ValueError(f"Line {line_num}: duplicate record_id")
        seen.add(row["record_id"])
        total += 1
        for domain in row["domains"]:
            counts[domain] = counts.get(domain, 0) + 1
    return {"records":total, "domain_counts":counts, "taxonomy_version":taxonomy["version"]}


def main() -> None:
    p = argparse.ArgumentParser(description="Validate Phase 2K global taxonomy or annotations")
    p.add_argument("--taxonomy", default="taxonomies/global_intelligence_v1.json")
    p.add_argument("--annotations", help="Optional global annotations JSONL to validate")
    args = p.parse_args()
    tax = load_taxonomy(args.taxonomy)
    print(json.dumps(validate_jsonl(args.annotations,tax) if args.annotations else {"taxonomy_validated":tax["taxonomy_id"], "version":tax["version"],"domains":len(tax["domains"]),"defense_event_types":len(tax["defense_event_types"])}, indent=2))

if __name__ == "__main__":
    main()
