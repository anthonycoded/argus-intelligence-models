# AIC-1 Phase 2G — Government source discovery adapter

This **additive patch** introduces `src/government_sources.py` and six tests. Extract it into the existing `argus-intelligence-models` directory. It does not replace or edit any approved records, provenance, reviews, topic files, or the existing Phase 2E importer.

## Scope and safeguards

- **Offline-only** RSS/Atom parsing. Obtain official XML feeds using your browser or other authorized means and save them locally. The adapter makes **zero HTTP requests** and accesses no Argus-Core service, database, API key, or credential.
- Sources are restricted to HTTPS URLs under `defense.gov`, `state.gov`, `gao.gov`, `congress.gov`, `dni.gov`, or `navy.mil` (including subdomains); the source/feed's own authenticity must still be checked before use. This is a discovery allowlist, **not a license allowlist**.
- 2 MiB XML size limit; DTD/entity declarations rejected; RSS and Atom entries parsed for **metadata only**. Feed descriptions, pages, and entire articles are **not copied into training**.
- Records discovered are **not** in the human-review queue. You must separately create rights-reviewed source text (or an original human-authored summary) to prepare a candidate, then use the existing batch importer.
- A rights note records your statement only; the Phase 2F rights control remains `unverified` until separately attested after source verification. Human annotation is still required.
- This basic XML parser is intended for trusted, locally saved feeds, not hostile XML at arbitrary scale. Do not bypass the size/DTD checks.

## Verify

```bat
python -m pytest -q
python -m src.government_sources --help
```

If you had **42 passing tests**, the six new tests should bring the total to **48**.

## Discovery

1. Obtain an actual official RSS or Atom feed file from an authorized government source and save it as `data/incoming/official_feed.xml`. Confirm the site and HTTPS URL independently.
2. Run:

```bat
python -m src.government_sources discover data/incoming/official_feed.xml --output data/discovery/official_batch_001.jsonl
```

3. Inspect `data/discovery/official_batch_001.jsonl` in VS Code. This file contains only source URLs, titles, raw publication timestamps, and discovery identifiers. Zero matches is possible; some official feeds redirect to article hosts outside the default allowlist and require a deliberate code review before expanding supported hosts.

## Prepare a single candidate

Read an official article or report, verify the intended use, and create **your own** accurate summary in `data/incoming/selected_summary.txt`. Do not copy third-party copyrighted passages into a training corpus without appropriate permission. Choose the matching `discovery_id` from the discovery JSONL, and a meaningful event grouping:

```bat
python -m src.government_sources prepare data/discovery/official_batch_001.jsonl DISCOVERY_ID --text-file data/incoming/selected_summary.txt --content-type human_summary --rights-note "Human-authored summary; source rights require separate verification" --event-group-id taiwan-event-001 --batch-output data/candidates_batch_002.jsonl
```

Only then enqueue with the **existing importer**:

```bat
python -m src.candidate_import import data/candidates_batch_002.jsonl --topic topics/taiwan_military_v2.json
python -m src.review_queue list
python -m src.dataset_integrity report
```

All candidates remain pending. `prepare` neither labels them nor clears training rights. A human summary of copyrighted material may have different rights considerations from copied text; verify applicable permissions and do not treat this adapter as legal clearance.

## Future extension

Once the discovery-to-review workflow is tested with 20 samples, add narrowly scoped, authenticated, read-only Argus-Core export support. Keep remote fetching and content extraction in Argus-Core's existing hardened transport rather than introducing a second unreviewed network client here.
