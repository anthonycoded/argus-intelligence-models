# AIC-1 Phase 2K — Global Intelligence Taxonomy (additive patch)

## Purpose

Global defense intelligence, **not** China/Taiwan only. This adds an independent domain/event annotation schema alongside the pre-existing Taiwan topic-relevance workflow. No current annotations, rights statuses, topic definitions, feed adapters, or embedding rankings are rewritten. No model is trained by this patch.

## Install

Extract the ZIP **into the existing project root** and merge folders. From an active venv:

```bat
python -m pytest -q
python -m src.global_taxonomy --taxonomy taxonomies/global_intelligence_v1.json
```

Expected global taxonomy report: 5 domains and 8 defense event types. The combined historical suite should have 82 tests (69 old + 13 new), assuming your original environment is intact.

## Schema

- `domains`: multi-label `defense`, `economics`, `geopolitics`, `cybersecurity`, `other`. `other` cannot coexist with other domains. Economics/cyber/geopolitics detailed event taxonomies are **future work**.
- `defense_event_types`: 8 multi-label categories. Non-defense items have an empty defense-event list; verified defense annotations need at least one.
- `countries`: ISO-3166-style two-letter codes plus explicit role (`actor`, `host`, `participant`, `target`, `affected`, `mentioned`). **Membership in ISO 3166 isn't validated yet.** Do not conflate country mentioned with perpetrator/actor. Empty countries is permissible if unestablished.
- `organizations`, `event_location`, `event_date`: extracted structured fields, nullable where not established.
- `evidence_status`: reported, independently_corroborated, disputed, unknown. Reported claims must remain attributed; annotation is **not** independent verification that an event happened.
- `annotation_status`: pending or human_verified. Only reviewers can mark a record human_verified; programmatic schema checks cannot prove human action took place.
- `taxonomy_version`: `aic-global-v1`.

This is **event classification**, not topic relevance. The same USS Bulkeley article may have `defense`/`military_exercise` globally and `unrelated` for the Taiwan-specific topic. Each schema is stored separately and has its own version.

## First draft annotation

Use `examples/global_annotation_TEMPLATE.json` to create *a draft*. Replace template fields with evidence extracted from a real source. To validate one or more complete draft records, save **one JSON object per line** to `data/global_annotations/pilot.jsonl` and run:

```bat
python -m src.global_taxonomy --annotations data/global_annotations/pilot.jsonl
```

The default pilot file is **not** shipped with labels. Do not promote old topic labels, model predictions, or placeholders automatically. Existing rights/provenance controls are unchanged. Current annotations are not assumed training eligible.

## Next recommended work

1. Extend the review queue for a *separate*, versioned global annotation approval step with audit history.
2. Human-annotate representative examples from every continent and hard negatives. Avoid sampling only high semantic-similarity articles.
3. Add a defense-vs-nondefense model baseline before multi-label event-head training. Measure quality by country and event type.
4. Define detailed economic taxonomy as a subsequent version, keeping domain labels stable.
