# Phase 2O: first global candidate pilot

This preparation run collected 40 unique RSS/Atom metadata records and prepared
24 pending human-review packets. It performed local embedding inference, not
classifier training. No annotation was approved, no rights were cleared, and no
article body was downloaded. All article-level labels remain undetermined.

Phase 2N was already committed as
`876fce2cea1a1d647a9e8333e327381b44287673`; no duplicate baseline commit was made.
This phase adds only an opt-in source configuration and documentation to version
control. Generated feeds, rankings, caches and review packets remain ignored.
Phase 2L/2M training, approval, provenance and rights safeguards are unchanged.

Validation: the pre-flight suite passed all 362 tests in 183.64 seconds; the final
suite passed all 362 in 186.92 seconds. Ranking and sampling JSONL replayed
byte-for-byte; saved feed parsing reproduced all 40 records apart from collection
time. SHA-256 checks confirmed all 17 protected files unchanged, including the
five legacy approvals, existing provenance/policy sidecars, and training/review
safeguard files. No new product code or test framework was needed for this pilot.

## Actual collected coverage

Collection timestamps are recorded in UTC, starting `2026-11-23T04:48:27+00:00`
(November 22 in America/New_York). URLs below were fetched successfully through
the existing DNS-pinned, HTTPS-only, bounded XML collector.

| Publisher | Publisher country / origin region | Valid metadata | Selected |
| --- | --- | ---: | ---: |
| [US Navy](https://www.navy.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=1067&max=10) | US / North America | 10 | 8 |
| [UK Government](https://www.gov.uk/search/news-and-communications.atom) | GB / Europe | 20 | 8 |
| [SAnews](https://www.sanews.gov.za/south-africa-news-stories.xml) | ZA / Africa | 10 | 8 |

Publisher origin is not event geography. All 40 records are English and from
government publishers; independent commercial journalism and multilingual coverage
are absent. Event countries, confirmed defense/nondefense balance and event-type
coverage require human review. Representativeness is not established.

Eight configured feed endpoints were attempted. Beehive NZ returned an unacceptable
MIME type, India PIB failed the pinned HTTPS connection, CISA returned non-200,
and Australia's DTA closed its connection. Singapore NEA returned valid XML with
23 HTTP article links; the HTTPS-only policy rejected all 23. Their raw feed is
retained for audit, but they are not eligible candidates. No security checks were
relaxed. Asia, Oceania and South America have no usable publisher coverage in this
batch. Defense News remains supported but was not included in this new poll.

Official source directories and reuse context were inspected, including
[SAnews](https://www.sanews.gov.za/),
[SAnews user policy](https://www.sanews.gov.za/content/user-policy), and
[GOV.UK reuse guidance](https://www.gov.uk/help/reuse-govuk-content).
These checks do not clear training rights. RNZ and Al Jazeera were excluded after
reviewing their usage restrictions. Each eventual content representation still
needs an explicit handling basis and separate training-rights review.

## Artifacts on this workstation

All paths below are local ignored artifacts, not committed dataset distributions.
Keep the complete directory if moving the review batch to another workstation.

- `data/discovery/phase2o_001/review/INDEX.md`: 24 clickable review packets.
- `review/001/REVIEW.md` through `review/024/REVIEW.md`: exact per-candidate commands.
- Each packet contains source/sampling provenance in `packet.json`, an empty
  `content.txt` and the Phase 2M annotation scaffold in `annotation.json`.
- `poll-us_navy_news`, `poll-uk_government`, `poll-sa_government_news`: raw feeds,
  metadata JSONL and immutable poll manifests with timestamps and SHA-256 hashes.
- `poll-sg_nea`: retained raw feed and zero accepted candidates.
- `source_checks.json`, `source_checks_round2.json`: successful and failed attempts.
- `ranking_initial`: all 40 candidate records, including all low scores.
- `sample`: seeded 24-item sample and selection design manifest.
- `ranking_replay`, `sample_replay`: verification runs; JSONL bytes match originals.
- `pilot_report.json`: machine-readable counts, model identity and limitations.
- `review/packet_hashes.json`: initial packet hashes, before human edits.
- `build_review_packets.py`: one-time artifact recipe; refuses to overwrite review work.

No source content has yet been registered in the Phase 2M store. There are zero
global drafts, zero global approvals and zero eligible global examples. Empty
scaffolds are intentionally invalid and cannot be approved. The five legacy Taiwan
approvals remain separate and are not global labels.

## Discovery and reproduction

Activate `.venv` from the repository root. Use new output paths for every rerun;
existing bundles are never silently overwritten.

```powershell
.\.venv\Scripts\Activate.ps1
# Explicit opt-in live poll; requires permitted network access.
python -m src.global_feeds --config configs/global_pilot_001.json --output data/discovery/phase2o_002/poll
# Offline parser replay of the saved feeds (new collection timestamp).
python -m src.global_feeds --config configs/global_pilot_001.json --feed-files data/discovery/phase2o_001/saved_feed_files.json --output data/discovery/phase2o_001/offline_replay
```

The real ranking used cached `sentence-transformers/all-MiniLM-L6-v2` on CPU:

- Hugging Face snapshot: `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`.
- Exact local directory SHA-256: `23c61c55d84d9ab0045288ba589018e80ff90cf894514f5676e351c14624d255`.
- Profile: `profiles/global_intelligence_v1.json`, 26 global multi-domain queries.
- Profile SHA-256: `8cdb4e2fc8a172c4c488896150184544e9586f4102e4f3c2c24c24b11d4223fd`.
- Sample JSONL SHA-256: `da8780741af6ad18ce4599af7db3e009a2c6db8e4eb99a2a9e50cbd9cebdffc5`.

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:HF_HUB_DISABLE_TELEMETRY='1'
$env:OMP_NUM_THREADS='2'
$env:MKL_NUM_THREADS='2'
$model = 'C:/Users/barbe/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots/1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
python -m src.global_discovery --inputs data/discovery/phase2o_001/poll-us_navy_news/discovery.jsonl data/discovery/phase2o_001/poll-uk_government/discovery.jsonl data/discovery/phase2o_001/poll-sa_government_news/discovery.jsonl --output data/discovery/phase2o_001/ranking_new --cache-dir data/embedding_cache/phase2o_001 --model $model --model-revision 23c61c55d84d9ab0045288ba589018e80ff90cf894514f5676e351c14624d255
python -m src.global_sampling sample --ranking data/discovery/phase2o_001/ranking_initial --output data/discovery/phase2o_001/sample_new --seed 42 --per-stratum 4 --publisher-cap 8 --region-cap 8 --max-total 24
```

The 24 selections contain 14 low-score (`<0.3`) and 10 middle-score (`0.3–0.6`)
records. The full pool contains 30 low and 10 middle records. Query hints inform
sampling only; similarity is neither classification truth nor confidence.
Publisher and region caps bound each publisher's share to eight items. First-stage
stratum probabilities are retained, while final inclusion probabilities are
explicitly unknown after interacting caps. Do not use these as an unbiased survey.

The queue includes defense-discovery candidates and apparent civilian developments
for independent assessment. Packet suggestions flag possible lexical hard negatives,
such as the Marine Parade place name and an AAIB investigation team deployment,
plus ceremonies and low-score exploration. These are review questions, not confirmed
negative labels. No defense/nondefense quota can be claimed before human review.

## Human review

Start with `data/discovery/phase2o_001/review/INDEX.md`. Each packet's `REVIEW.md`
has an exact candidate ID and commands. Read permitted source text independently,
fill `content.txt`, then annotate that exact representation with evidence spans,
global domains and event scope. Use `permitted_excerpt` only with an actual basis;
choose `human_summary` only for text actually written by the human reviewer.
Do not paste restricted bodies or represent model-generated summaries as human work.

The per-item commands register the supplied text through `src.global_sampling prepare`,
create a draft using `src.global_review draft`, and display it for inspection.
Only an actual reviewer may then run the explicit confirmation:

```powershell
python -m src.global_review approve $draft.draft_id --reviewer YOUR_ACTUAL_REVIEWER_ID --confirm-human-review
python -m src.global_review eligibility
```

Approval is separate from rights clearance. A reviewed article can remain blocked
from dataset export. No dataset was frozen or exported in this phase because no
global examples currently satisfy approval and rights requirements.

## Next collection rounds

1. Complete independent review of these 24 candidates; adjudicate ambiguous cases
   and separately document rights decisions with evidence.
2. Verify additional opt-in publishers in Asia, Oceania and South America, including
   reputable independent journalism with suitable access and handling terms.
3. Collect repeated immutable polls with all records retained. Review in seeded
   batches, including civilian developments, difficult negatives and low scores.
4. Build toward 200–500 independently approved examples with explicit coverage
   diagnostics, content rights, duplicate identities and event grouping. Use a
   second reviewer for ambiguous labels and a quality-control subset.
5. Only after sufficient eligible groups and label support exist, freeze a global
   dataset with group-aware splits. Report snapshot eligibility separately from
   readiness for supervised training and evaluation. No classifier training here.
