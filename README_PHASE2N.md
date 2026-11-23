# Phase 2N: global discovery and reproducible dataset preparation

This phase prepares research inputs. It does not train a model, evaluate a trained
classifier, change Argus-Core, convert legacy topic labels, or clear source rights.
The platform remains multi-domain/worldwide; defense versus nondefense is simply
the first supervised target. Economic, geopolitical and cyber annotations remain
in the exported records alongside defense labels.

Preflight: Phase 2M was already committed as `d29b5de`; the working tree was clean.
Its full 274-test suite passed before development. No Phase 2M commit was needed.

## Global query profiles and local ranking

`profiles/global_intelligence_v1.json` contains 26 English queries: two for each
of defense, economics, geopolitics and cybersecurity, and two per defense event
type in taxonomy v2. Profiles bind the taxonomy document hash, query IDs, text,
keywords, language declarations and scoring configuration. Use a NEW profile
version for changes; outputs embed the complete profile and its canonical hash.
There is no default China/Taiwan geographic objective.

```powershell
python -m src.global_discovery --inputs data/discovery/global_poll_001/discovery.jsonl --output data/discovery/global_rank_001 --model-revision MODEL_COMMIT_40_HEX
```

Replace `MODEL_COMMIT_40_HEX` with the actual immutable revision of your locally
cached model; `main`, `latest` and omitted revisions are refused. The default
model name is `sentence-transformers/all-MiniLM-L6-v2`. No downloading fallback
exists: inference uses local sentence-transformers on CPU, with remote code
disabled and a recorded sequence limit. This task's tests use injected synthetic
encoders and never import/load a model.

For an explicit local model DIRECTORY, pass `--model PATH` and use the SHA-256
directory fingerprint returned by this offline helper:

```powershell
python -c "from src.global_discovery import model_directory_hash; print(model_directory_hash('C:/models/my-local-model'))"
```

The fingerprint streams file hashes without loading weights as a model. Directory
drift is rejected before encoding. Hub revision identity relies on the immutable
cached revision and recorded package versions; this is not a signature check.

Ranking defaults to titles only. Optional records with `source_ref_id` require
`--store PATH`, then use validated Phase 2M registered content. Raw discovery
`article_text` fields are never automatically ingested into model input. Every
ranking row records:

- Model name/revision, backend identity, package versions and inference settings.
- Profile version/hash, query IDs/scores, domain/event-type score aggregates.
- Max-cosine, keyword and weighted hybrid scores and exact scoring configuration.
- Exact ranking-input hash; registered article revision/provenance bindings where
  available. Title-only rows explicitly have NO full-article revision hash.
- A declared supported/unknown/unsupported language flag.

Cosine/hybrid scores are ordering evidence, NOT probabilities, confidence, labels,
or event verification. English queries/model quality have not been validated for
other languages. Unsupported-language candidates remain visible for manual review.
Long registered content is truncated by the recorded model sequence limit.

Canonical URL deduplication matches intake. A titleless entry does not consume its
URL, so a later usable title survives. The first usable canonical occurrence wins
within an invocation; preserve input order when reproducing a run. Across runs,
changed exact input/content/profile/model identity invalidates the cache key.
Caches verify stored identity and vector validity. Injected test encoders need
separate named backend identities and cannot share production cache keys.

Bundles are new directories containing `ranking.jsonl` and `manifest.json`; existing
outputs are refused. Pilot limits: 100 input files, 1,000 usable records, 128 queries,
and 128 MiB ranking output. Cache hits need no model import.

Explicit optional topic-conditioned ranking remains available:

```powershell
python -m src.semantic_ranker --mode topic --topic topics/taiwan_military_v2.json --inputs data/discovery/defensenews_001.jsonl --output data/discovery/topic_rank_001 --model-revision MODEL_COMMIT_40_HEX
```

`src.semantic_ranker` now defaults to the SAME global CLI. Its old JSONL-output CLI
is deprecated; `--output` now means a new bundle directory. The historical Python
`rank(..., topic=...)` API is retained for injected research encoders, but refuses
unversioned real model loading. Existing unit-test contracts remain intact.

## Opt-in source collection and actual verified coverage

`configs/global_feeds.json` lists the existing Navy and Defense News sources,
DISABLED by default. Their `local_archive` verification means only that historical
XML/metadata already exists in this repository, not that endpoints are live today.
Set `enabled` explicitly only after checking intended source use. New feeds must
also have an explicit operator verification assertion and exact article-host
allowlist, publisher name/country, origin region and language metadata.

`examples/global_feeds_TEMPLATE.json` illustrates Kenyan and Brazilian configuration
using FICTIONAL example.org endpoints. They are disabled/unverified and must be
replaced and checked. No new international endpoint is claimed verified or polled.
The parser/configuration supports publishers worldwide without country-specific
collection logic; endpoint support and legal handling remain operator decisions.

```powershell
python -m src.global_feeds --config data/my_enabled_feeds.json --output data/discovery/global_poll_001
```

For an offline reproducible poll, supply a JSON object mapping enabled feed IDs
to saved XML paths. The optional map disables network fetching entirely:

```powershell
python -m src.global_feeds --config data/my_enabled_feeds.json --feed-files data/feed_files.json --output data/discovery/global_poll_001
```

Transport uses exact configured HTTPS endpoints, no credentials/nonstandard ports,
no proxies or redirect following, certificate verification and original-host TLS
SNI. DNS resolves once; ANY nonpublic/mixed/special-use answer is rejected. The
connection pins those validated socket addresses. Reads have a byte cap, socket
timeout and a wall-clock watchdog. Compressed/non-XML responses are refused.
Both generic RSS/Atom parsing and existing adapters retain DTD/entity rejection,
including UTF-16, and tree/item limits. Article links must match exact configured
publisher hosts. Feed descriptions and full article bodies are not imported.

Every poll freezes configuration, raw feed hashes, original XML and metadata.
Explicit RSS pubDate/Atom published timestamps are normalized only when parseable
with a timezone. Atom updated and collection time are not promoted to publication
time. Unknown publication dates remain null through review intake and stress export.
There is no generic incremental seen-state migration in this phase; new polls may
rediscover URLs and the ranker canonicalizes/deduplicates them. A failed configured
feed aborts the new poll instead of publishing an apparently complete partial poll.

`src.feed_automation` now delegates its CLI to this global collector; historical
topic-priority Python APIs remain available explicitly. Old `--state`, `--feed-dir`
and `--low-sample-pct` CLI flags are deprecated. The Navy/Defense News adapter
functions remain unchanged. The Defense News regional path is configuration data
for the historically verified feed, not a restriction on the new collector.

Actual current coverage remains limited:

- Existing discovery archives contain 20 unique URLs: 10 Navy and 10 Defense News.
- Both publishers are US-based, and existing configured language is English.
- Publisher origin is NOT article/event geography. Stories mention other countries,
  but those mentions have not established reviewed global event coverage.
- No global approvals or rights-cleared global cohort existed at preflight. The five
  legacy Taiwan relevance records are never used as global labels.
- Economics/cyber/general-news breadth, non-US publishers, multilingual quality,
  historical depth and representative regional event coverage remain unverified.

No live source or model network request was made during this implementation.

## Diversity sampling and annotation-queue preparation

```powershell
python -m src.global_sampling sample --ranking data/discovery/global_rank_001 --output data/discovery/global_sample_001 --seed 42 --per-stratum 2 --publisher-cap 8 --region-cap 40 --max-total 100
```

Sampling stratifies on publisher-origin metadata assertions, publisher, declared
language, UNVERIFIED query hint and score range (low < .3, middle < .6, high >= .6).
It samples uniformly without replacement within fixed strata using an explicit
seed, then balances regions, publishers, score buckets and hints under caps/budget.
Consequently high-score items from a dominant publisher/region cannot simply fill
all review slots. Missing origin fields stay `unknown`; no country/region is inferred
from names or titles. Metadata assertions and query hints are not ground truth.

Low-score items support randomized exploration. Semantic/keyword disagreement is
flagged only as a hard-negative CANDIDATE; only human global annotation can establish
a negative. There is no rejection/drop rule based solely on a semantic threshold.

Each selected row records seed, stratum population/quota, reasons and first-stage
inclusion probability. When no caps/budget bind, final probability is quota/population.
When constraints interact, final probabilities are null rather than invented.
Diagnostics expose missing regions, publisher/language/score-range distributions,
unverified hints and quota populations; representativeness is always unestablished.
Global sampling refuses topic-conditioned ranking bundles.

Supply independently permitted text for a selected candidate:

```powershell
python -m src.global_sampling prepare --sample data/discovery/global_sample_001 --candidate-id CANDIDATE_ID --store data/global_annotations --text-file data/permitted_content.txt --content-type human_summary --rights-note "Accurate handling assertion; training rights remain unverified"
```

This creates a Phase 2M source reference and an append-only `intake` receipt with
sampling provenance and state `awaiting_human_global_draft`. It creates NO labels,
approval or rights decision. Missing publisher metadata requires explicit Phase 2M
registration rather than guessing an identity. Named Navy/Defense News publishers
retain their adapter URL allowlists. Existing identical source registration is
refused; no intake operation overwrites registered metadata/content.

Continue only through the Phase 2M human workflow:

```powershell
python -m src.global_review draft SOURCE_REF_ID data/completed_global_annotation.json
python -m src.global_review review DRAFT_ID
python -m src.global_review approve DRAFT_ID --reviewer HUMAN_REVIEWER --confirm-human-review
python -m src.global_review eligibility
```

Rights clearance remains a SEPARATE documented human decision. Neither personal use,
public accessibility, official origin, embeddings nor annotation approval grants it.

## Frozen global dataset construction

Complete `examples/global_cohort_TEMPLATE.json`. The cohort is an authoritative,
human-reviewed document with reviewer identity, UTC time and explicit grouping
confirmation. Each item names a current Phase 2M approval/source, reviewed language
and regions, one or more cross-article event/story group IDs, known duplicate-group
IDs, and optional sampling evidence. Article-local event instance IDs are NOT
automatically converted into global event groups. Multi-event articles can link
several reviewed groups; related components merge transitively.

Optional sampling evidence has this form (path relative to the cohort file):

```json
{"path":"discovery/global_sample_001","manifest_sha256":"REPLACE","candidate_id":"REPLACE"}
```

The selection, ranking identity and title/content revision must match the registered
source. Missing sampling evidence is explicit and is not fabricated for legacy or
manually recruited global examples.

```powershell
python -m src.global_dataset export --store data/global_annotations --cohort data/global_cohort.json --output data/snapshots/global_pilot_001 --seed 42
python -m src.global_dataset validate data/snapshots/global_pilot_001
```

Every selected row must have a current unchanged global approval and exactly one
current cleared, content-bound model-training rights decision. Missing/stale/
restricted/conflicting evidence aborts the export; rows are not silently skipped.
Only human global domain labels derive `defense` versus `nondefense`; all original
multi-domain/event labels and full approved annotation remain in the row. Mixed
taxonomy/policy definitions require an explicit migration and are refused.

The separate `aic-global-dataset-v1` manifest freezes content/reference/provenance,
approval, taxonomy/policy and rights identities/hashes, human grouping and sampling
evidence, inventory, diagnostics, seed and split algorithm. Authoritative cohort
and store remain required for validation. Text is exported only after clearance.
Dataset diagnostics include human regions/domains/event types/publishers/languages
and sampled score ranges; manually recruited examples are explicitly `not_recorded`.

A nonempty eligible cohort can be snapshotted without being ready for supervised
evaluation. Split readiness requires at least 30 eligible rows and 3 independent
components for EACH binary class, with both classes reserved in every split.
This is a sanity floor, not a statistical adequacy claim. `--require-splits` refuses
publication when it cannot produce ready splits; omit it to preserve a small
eligible snapshot with explicit readiness diagnostics. No trainer is implemented:
`training_supported` remains false, even when supervised splits are ready.

Components merge canonical source, exact content revision, normalized content
fingerprint, approval/source identity, human event groups and known duplicate
groups. Seeded deterministic allocation targets 70/15/15 and preserves every
component. Ratios are approximate for indivisible groups; difficult class/group
layouts can be conservatively refused. Output directories are never overwritten.
Dataset bounds are 1,000 cohort articles and 128 MiB prepared data.

Optional SEPARATE stress protocols:

```powershell
python -m src.global_dataset export --store data/global_annotations --cohort data/global_cohort.json --output data/snapshots/global_stress_001 --seed 42 --publisher-holdout "REVIEWED PUBLISHER NAME" --time-cutoff 2026-11-01T00:00:00Z
```

These produce independent development/holdout/quarantine outputs. Mixed components
and missing publication dates are quarantined. Collection time is never substituted
for publication time. Do not mix training assignments across these protocols.
Support counts and missing binary-class support are reported, not concealed.

Validation rechecks live global history, source content, rights inventories and
cohort bytes, reconstructs every dataset row and deterministic split, and compares
exact frozen files. Tampering with a file and merely updating its manifest hash
does not bypass original approvals/rights. New approvals or decisions can invalidate
old bundles conservatively; rebuild a new reviewed bundle rather than editing one.
The legacy topic trainer/manifest are unchanged and REFUSE this global manifest.

## Human-reviewed ranking benchmarks

```powershell
python -m src.ranking_benchmark --ranking data/discovery/global_rank_001 --store data/global_annotations --output data/discovery/ranking_benchmark_001 --k 10 --domain defense
```

Compare keyword, semantic and hybrid ordering using current human-reviewed global
annotations whose title/content revision matches. An optional `--event-type` selects
a reviewed defense category. Unreviewed or stale examples are NEVER negatives.
Precision@K is null unless K candidates exist and EVERY top-K candidate is reviewed.
Recall@K is null unless the ENTIRE candidate pool is reviewed and contains positives.
Defined recall is candidate-pool recall, not global-news recall. Reports include
available/reviewed counts, denominators, reviewed positive counts and insufficiency.

## Reproducibility and trust limits

All unit/integration tests use synthetic text, fake encoders, mocked DNS/HTTPS or
saved XML; no internet/model downloads or training. Phase 2L training guards,
legacy annotations/provenance and archived taxonomy/policy files are untouched.
There are no new dependencies or external services.

Hashes detect drift, not forgery by someone able to rewrite the entire authority
store. Grouping, publisher identity, regions/languages, source verification and
rights remain human/operator attestations. No semantic near-duplicate detector,
publisher-owner registry, automated entailment check or authentication is added.
Keep this a single-writer workflow; hostile filesystems/concurrent mutation are
unsupported. Preserve referenced store/cohort/ranking/sample paths when relocating
bundles. Models, profiles, inputs, software versions, seed and grouping must match
to reproduce outcomes; real ranking quality has not been measured in this task.

Use ignored `data/discovery/`, `data/global_annotations/` and `data/snapshots/`
destinations. Never stage datasets, feeds, caches, permissions evidence or secrets.
Phase 3 training is intentionally not begun.
