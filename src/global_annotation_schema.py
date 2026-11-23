"""Phase 2M strict article/event schema; archived Phase 2K validation is unchanged."""
import re
from datetime import date

from .global_io import document_hash, keys, string
from .global_taxonomy import validate_taxonomy

# Versioned local ISO 3166-1 alpha-2 vocabulary. Territory codes are identifiers,
# not assertions about sovereignty. Non-state actors belong in organizations.
COUNTRY_CODES = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ
CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR
GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP
KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ
NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW
SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ
UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
""".split())

BASE_FIELDS = {"domains", "defense_event_types", "countries", "organizations", "event_date",
               "event_location", "evidence_status", "rationale"}
ARTICLE_FIELDS = BASE_FIELDS | {"schema_version", "events", "event_coverage", "event_coverage_note", "evidence"}
POLICY_FIELDS = {"policy_version", "taxonomy_version", "taxonomy_sha256", "country_registry_version",
                 "country_codes", "event_rules", "guidance", "evidence_statuses"}


def validate_documents(taxonomy, policy):
    validate_taxonomy(taxonomy)
    keys(policy, POLICY_FIELDS, "global annotation policy")
    if (policy["policy_version"] != "aic-global-review-v1"
            or policy["taxonomy_version"] != taxonomy["version"]
            or taxonomy["version"] != "aic-global-v2"
            or policy["taxonomy_sha256"] != document_hash(taxonomy)
            or policy["country_registry_version"] != "aic-iso3166-alpha2-v1"):
        raise ValueError("Unsupported/mismatched taxonomy or annotation policy")
    if (not isinstance(policy["country_codes"], list)
            or any(not isinstance(c, str) for c in policy["country_codes"])
            or len(policy["country_codes"]) != len(COUNTRY_CODES)
            or set(policy["country_codes"]) != COUNTRY_CODES):
        raise ValueError("Country registry mismatch")
    if not isinstance(policy["event_rules"], dict) or set(policy["event_rules"]) != set(taxonomy["defense_event_types"]):
        raise ValueError("Every defense event category needs explicit rules")
    for value in policy["event_rules"].values():
        keys(value, {"include", "exclude"}, "event category rule")
        for explanation in value.values():
            string(explanation, "category explanation")
    string(policy["guidance"], "policy guidance")
    if policy["evidence_statuses"] != ["reported", "disputed", "unknown"]:
        raise ValueError("Independent corroboration requires a future cross-source evidence schema")


def _names(value, choices, name, empty=False):
    if (not isinstance(value, list) or (not value and not empty)
            or any(not isinstance(v, str) or v not in choices for v in value)
            or len(value) != len(set(value))):
        raise ValueError(f"{name}: empty, duplicate or unknown categories")


def _unit(unit, taxonomy, policy, event=False):
    keys(unit, BASE_FIELDS | ({"instance_id"} if event else set()), "event" if event else "article fields")
    _names(unit["domains"], taxonomy["domains"], "domains")
    _names(unit["defense_event_types"], taxonomy["defense_event_types"], "defense_event_types", empty=True)
    if "other" in unit["domains"] and len(unit["domains"]) != 1:
        raise ValueError("other is exclusive of substantive domains")
    if ("defense" in unit["domains"]) != bool(unit["defense_event_types"]):
        raise ValueError("Defense requires event categories; nondefense forbids them")
    if event and "defense_other" in unit["defense_event_types"] and len(unit["defense_event_types"]) > 1:
        raise ValueError("defense_other cannot mask a named category on one event")
    if not isinstance(unit["countries"], list):
        raise ValueError("countries must be a list")
    seen = set()
    for country in unit["countries"]:
        keys(country, {"code", "role"}, "country")
        if not isinstance(country["code"], str) or country["code"] not in COUNTRY_CODES:
            raise ValueError("Unknown ISO alpha-2 country code")
        if not isinstance(country["role"], str) or country["role"] not in taxonomy["entity_roles"]:
            raise ValueError("Unknown country role")
        pair = (country["code"], country["role"])
        if pair in seen:
            raise ValueError("Duplicate country/role")
        seen.add(pair)
    orgs = unit["organizations"]
    if not isinstance(orgs, list) or any(not isinstance(o, str) or not o.strip() for o in orgs) or len(set(orgs)) != len(orgs):
        raise ValueError("organizations must be unique nonempty strings")
    if unit["event_date"] is not None:
        if not isinstance(unit["event_date"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", unit["event_date"]):
            raise ValueError("event_date must be strict YYYY-MM-DD or null")
        date.fromisoformat(unit["event_date"])
    if unit["event_location"] is not None:
        string(unit["event_location"], "event_location")
    if not isinstance(unit["evidence_status"], str) or unit["evidence_status"] not in policy["evidence_statuses"]:
        raise ValueError("Unsupported evidence_status")
    string(unit["rationale"], "rationale")
    if event and (not isinstance(unit["instance_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", unit["instance_id"])):
        raise ValueError("Invalid article-local event instance_id")


def evidence_targets(article):
    targets = set()
    for prefix, unit in [("", article)] + [(f"/events/{i}", e) for i, e in enumerate(article["events"])]:
        for field in ("domains", "defense_event_types", "countries", "organizations"):
            targets.update(f"{prefix}/{field}/{i}" for i in range(len(unit[field])))
        for field in ("event_date", "event_location"):
            if unit[field] is not None:
                targets.add(f"{prefix}/{field}")
        if unit["evidence_status"] != "unknown":
            targets.add(f"{prefix}/evidence_status")
    return targets


def validate_article(article, taxonomy, policy, text, content_hash):
    validate_documents(taxonomy, policy)
    keys(article, ARTICLE_FIELDS, "global article annotation")
    if article["schema_version"] != "aic-global-annotation-v2":
        raise ValueError("Unsupported global annotation schema")
    _unit({k: article[k] for k in BASE_FIELDS}, taxonomy, policy)
    if not isinstance(article["events"], list) or len(article["events"]) > 100:
        raise ValueError("events must be a bounded list")
    ids = set()
    for event in article["events"]:
        _unit(event, taxonomy, policy, event=True)
        if event["instance_id"] in ids:
            raise ValueError("Duplicate article-local event instance")
        ids.add(event["instance_id"])
        if (not set(event["domains"]).issubset(article["domains"])
                or not set(event["defense_event_types"]).issubset(article["defense_event_types"])
                or not set(event["organizations"]).issubset(article["organizations"])
                or not {(c["code"], c["role"]) for c in event["countries"]}.issubset(
                    {(c["code"], c["role"]) for c in article["countries"]})):
            raise ValueError("Event labels/entities must be represented at article level")
    coverage = article["event_coverage"]
    if not isinstance(coverage, str) or coverage not in {"complete", "partial", "not_enumerated"}:
        raise ValueError("Explicit event_coverage required")
    if coverage != "complete":
        string(article["event_coverage_note"], "event_coverage_note")
    elif article["event_coverage_note"] is not None:
        string(article["event_coverage_note"], "event_coverage_note")
    if coverage == "not_enumerated" and article["events"]:
        raise ValueError("not_enumerated must not claim individual events")
    if coverage == "partial" and not article["events"]:
        raise ValueError("partial coverage requires at least one event")
    if coverage == "complete" and article["domains"] != ["other"]:
        for field in ("domains", "defense_event_types"):
            union = {v for e in article["events"] for v in e[field]}
            if union != set(article[field]):
                raise ValueError("Complete event coverage must account for all article labels")
    if "defense_other" in article["defense_event_types"] and len(article["defense_event_types"]) > 1 and len(article["events"]) < 2:
        raise ValueError("Mixed fallback/named categories require distinct explicit events")
    for field in ("event_date", "event_location"):
        if len({e[field] for e in article["events"] if e[field] is not None}) > 1 and article[field] is not None:
            raise ValueError(f"Multiple event values: keep article {field} null")
    targets, covered = evidence_targets(article), set()
    if not isinstance(article["evidence"], list) or not article["evidence"] or len(article["evidence"]) > 2000:
        raise ValueError("Bounded, nonempty source-grounded evidence required")
    for evidence in article["evidence"]:
        keys(evidence, {"target", "content_revision_sha256", "start", "end", "quote", "attribution"}, "evidence")
        if not isinstance(evidence["target"], str) or evidence["target"] not in targets:
            raise ValueError("Unknown/forged evidence target")
        start, end = evidence["start"], evidence["end"]
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
                or evidence["quote"] != text[start:end] or not text[start:end].strip()
                or evidence["content_revision_sha256"] != content_hash):
            raise ValueError("Forged/stale evidence content revision, offsets or quote")
        string(evidence["attribution"], "evidence attribution")
        covered.add(evidence["target"])
    if covered != targets:
        raise ValueError(f"Missing source evidence for fields: {sorted(targets - covered)}")
    return article
