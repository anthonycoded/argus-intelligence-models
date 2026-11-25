# Phase 3C: experimental local inference and shadow evaluation

Status: implemented for opt-in research. No production feature was enabled, no
model was trained/downloaded, and no annotation or training rights were changed.
The existing review dashboard remains independent on port 6910.

## Repository audit and decision record

Verified repositories at preflight:

| Repository | Branch | HEAD | Initial work |
| --- | --- | --- | --- |
| AIC-1 | main | e102e33 | Untracked user `experiments/` and `aic1_synthetic_v2/`; preserve |
| Argus-Core | architecture/separate-global-chess | a774b4d | Clean |
| Argus | main | c93f029 | Unrelated Windows tunnel/startup work; preserve |

AIC-1's `experiments/defense_classifier.py` trains at import, uses an unpinned
encoder name and writes a pickle head. It must never be imported by a service.
`experiments/semantic_search.py` searches 160 synthetic records with an in-memory
NumPy index; those records are not intelligence or human-reviewed gold.

Core's existing paths are `backend/app/api/v1/ai.py`,
`backend/app/clients/ollama_client.py`, `backend/app/core/auth.py`, and its
existing article extraction/security clients. Normal `/api/v1/ai/generate`
continues to return exactly `status`, `model`, `result`; it never invokes AIC-1.
Existing provider errors and admission controls remain unchanged.

Argus's actual client is `backend/app/clients/core.py`; its classification paths
are `backend/app/services/classification.py` and `article_classification.py`,
with policy contracts in `military_semantics_policy.py` and
`military_prompt_contract.py`. Topic relevance and global military-subject
assessments do not establish the binary global-defense target used here.
No Argus files were changed. The optional UI panel is deferred because it is
unnecessary for the isolated slice and Argus has unrelated ongoing changes.
Intendo was left intact at the operator's explicit direction.

Decision: use a separate authenticated loopback service with a pinned numeric
logistic head and local safetensors encoder. Core has separate opt-in shadow and
retrieval routes; no operational pipeline is hooked automatically. HTTP schemas
are versioned independently, with strict validation at both ends. SQLite journals
retain bounded metadata and hash chains rather than copies of article bodies.
No RAG orchestration, hosted services or database migrations are introduced.

## Artifact conversion and trust limits

The operator authorized one isolated conversion of the locally trained head:

* Source: `experiments/models/defense_head.joblib`
* Source SHA-256: `3ff5a564931b6db164f4fa64810d30ba6d632f46942410d425f30c0037fd6bb5`
* Numeric head SHA-256: `a13cab03e3304a2966a5821115ec127078652cf54273e0c554e72cccbee330cd`
* Encoder revision: `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`
* Encoder tree SHA-256: `cdf609f5ee2eeb7204517d51b88b8079fb53624531a28ee74c524b58acf36caa`

`tools/prepare_conversion_image.py` downloaded public Linux CPython 3.12 wheels
from official PyPI, verified their published SHA-256 values, then installed them
with `--no-index --require-hashes --only-binary=:all:` in a `--network none`
build based on a cached digest-pinned public Python image. No model, source
artifact, repository, secret or production data entered that build context.
See ignored build evidence for exact versions, URLs, wheel hashes and image ID.

`tools/convert_head_isolated.py` verified the source hash and training output path
before creating a worker. The worker had network `none`, a read-only root,
UID/GID 65534, all capabilities dropped, no-new-privileges, one CPU, 512 MiB
memory+swap limit, 32 PIDs, and 64 MiB non-executable temporary storage. Its only
read-only host mount contained the hash-verified head, standalone converter and
fixed numeric probe/config JSON. No Docker socket or host environment was passed.
The controller inspected these conditions before execution, bounded output to
64 KiB per stream and execution to 60 seconds, validated numeric output after
termination, and removed the exact worker container. Pickle was never loaded in
the host Python environment or in any production service. The old host converter
is explicitly disabled, even when passed its former confirmation flag.

The 19 fixed feature vectors include zero, signed basis, dense, alternating and
deterministic normalized probes. Predictions all matched; maximum absolute
probability difference was `1.1102230246251565e-16` against tolerance `1e-10`;
there were no threshold ties. This verifies sampled numerical parity, not
empirical accuracy or calibration. Coefficients/intercept/class ordering were
copied without fitting. Artifacts and evidence are frozen under ignored
`data/inference/converted-head-v1/{head.json,trust-manifest.json}`.

Provenance is operator attestation plus the verified expected path/hash and
observed training script. The old training script had no pinned encoder revision
or training manifest. Current dataset/split hashes are observations, not proof of
historical inputs. The pinned cached encoder is structurally compatible, but its
identity at original training time cannot be independently established. Docker
shares a Linux kernel; this is not a guarantee against runtime/kernel exploits.
No deployment approval or rights clearance follows from conversion.

## Wire contract and security boundaries

`src/inference_contracts.py` is the executable Pydantic contract;
`examples/inference/classify-request.json`, `classify-response.json` and the
generated `contracts.json` provide public synthetic examples and JSON schemas.

| AIC-1 endpoint | Requirements/result |
| --- | --- |
| GET /health/live | Minimal loopback liveness; no token |
| GET /health/ready | Dedicated X-API-Key; pinned runtime identity, index readiness |
| POST /v1/classify | Exact UTF-8 content digest; binary experimental uncalibrated score |
| POST /v1/embeddings | Same input; normalized 384-vector and encoder/content identity |
| POST /v1/retrieve | Same input + pinned index SHA-256, top_k 1–10; source bindings/excerpts |

Input supplies exactly one of bounded `text` or an authorized registered
`source_ref_id`, stable article/request IDs, exact content hash,
`authorized_for_processing: true`, and a handling basis. This is an explicit
caller attestation, not automatic legal verification. A reference additionally
requires a matching permitted index entry; stale/missing provenance, content or
permissions fail closed. Raw text does not receive a human-gold match.

Only loopback peers with the exact configured Host are accepted; browser Origin,
query strings and arbitrary endpoint selection are rejected. Service authentication
precedes body parsing. Bounds: 128 KiB request body, 16,000 supplied text characters,
256 model tokens, one inference worker, one admitted inference at a time, CPU
threads=1, default 5-second inference deadline (maximum 30). A deadline does not
kill native inference: the slot remains occupied until work ends; a hung native
worker requires operator restart. There is no OS-level RAM limit for the Windows
service; the container conversion's RAM limit is a separate boundary.

The encoder is local-only/offline, disallows remote code and executable weight
formats, and is pinned by revision and complete tree hash. Numeric heads are
strictly validated and content-hash pinned before model loading. Startup cannot
fit/download/convert a model. Missing state leaves readiness/inference unavailable.
No access logs, raw request/error echo, article bodies or tokens enter journals.
Journals stop at 10,000 events pending operator review; UPDATE/DELETE triggers and
hash chains detect ordinary mutation/restart corruption. They are not WORM:
an administrator can replace an entire filesystem snapshot or rewrite chains.

Retrieval indexes are frozen, hash-pinned, at most 1,000 source references/8 MiB,
and tied to the exact encoder, registered representation and provenance. Every
search revalidates permissions and current source state. An explicit processing
permission is required independently of training rights; restricted/conflicting
rights block use. Unverified training rights are never cleared. Synthetic
fixtures require explicit fixture mode at both ends and remain visibly marked.
No training JSONL is automatically indexed. Excerpts are exact first 600 Unicode
code points, not a claim of semantic evidence grounding. Cosine similarity is
ranking evidence, not confidence. Source URLs are returned for display, never
fetched by the service or Core client.

## Windows local startup (operator opt-in)

Use the existing environment or install `requirements-inference.txt` in a
separate Python 3.12 environment. This phase did not install packages into the
existing environment. Dependency declarations bound major versions; the trust
manifest records exact conversion versions, not a portable inference lockfile.

From AIC-1, generate a dedicated session token and retain it locally for Core:

```powershell
$env:AIC_INFERENCE_TOKEN = .venv/Scripts/python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
$encoder = 'C:/Users/barbe/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots/1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
.venv/Scripts/python.exe -B -m src.inference_service --port 6920 --head data/inference/converted-head-v1/head.json --head-sha256 a13cab03e3304a2966a5821115ec127078652cf54273e0c554e72cccbee330cd --encoder $encoder --revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 --state-root data/inference/service-v1
```

Keep tokens out of source, command literals, reports and shared console history.
Readiness in another authorized session:

```powershell
Invoke-RestMethod http://127.0.0.1:6920/health/ready -Headers @{'X-API-Key'=$env:AIC_INFERENCE_TOKEN}
$body = Get-Content examples/inference/classify-request.json -Raw
Invoke-RestMethod http://127.0.0.1:6920/v1/classify -Method Post -ContentType 'application/json' -Headers @{'X-API-Key'=$env:AIC_INFERENCE_TOKEN} -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

Core settings are operator-only, disabled by default. Set these in the environment
of a **separate experimental Core instance**, using its existing local startup and
database/readiness conventions. Do not restart a production instance for a smoke:

```powershell
$env:AIC1_SHADOW_ENABLED='true'
$env:AIC1_BASE_URL='http://127.0.0.1:6920'
$env:AIC1_TOKEN=$env:AIC_INFERENCE_TOKEN
$env:AIC1_CLASSIFIER_SHA256='a13cab03e3304a2966a5821115ec127078652cf54273e0c554e72cccbee330cd'
$env:AIC1_ENCODER_REVISION='1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
$env:AIC1_ENCODER_SHA256='cdf609f5ee2eeb7204517d51b88b8079fb53624531a28ee74c524b58acf36caa'
$env:AIC1_SHADOW_AUDIT_PATH='C:/Users/barbe/Desktop/projects/argus-core/backend/.aic-shadow/research.sqlite3'
$env:AIC1_TIMEOUT='3'
```

Core `/api/v1/ai/aic-shadow` uses the normal application X-API-Key with
`ai:generate`; `/api/v1/ai/aic-retrieve` requires both `ai:generate` and
`articles:extract`. These are application credentials, distinct from the service
token. Separate shadow quotas apply. Payloads cannot override endpoint URLs.
Transport is fixed loopback HTTP, bounded total timeout (maximum 10 seconds),
64 KiB response, no proxies, redirects or retries. Failure returns experimental
unavailability and cannot alter normal Ollama responses/operational decisions.
Default OpenAPI remains unchanged because the router is absent when disabled.

## Retrieval provisioning

No real source permission was granted and no real-source index was built in this
phase. An operator must first establish permitted processing and prepare a JSON
manifest with `schema_version: aic-processing-permissions-v1`, `permissions: [...]`.
Each permission requires the exact four-field binding returned by `load_source`,
scope `local_inference_and_retrieval`, `permitted: true`, reviewer identity, UTC
review timestamp, documented handling basis, and `synthetic_fixture: false`.
Do not copy synthetic attestations onto publisher material or infer permission
from accessibility, public service origin, personal use or annotation approval.

```powershell
.venv/Scripts/python.exe -B -m src.inference_retrieval --permissions '<reviewed-permission-manifest.json>' --store data/global_annotations --head data/inference/converted-head-v1/head.json --head-sha256 a13cab03e3304a2966a5821115ec127078652cf54273e0c554e72cccbee330cd --encoder $encoder --revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 --output data/inference/permitted-index-v1 --version permitted-index-v1 --confirm-permitted-use
```

Start AIC with `--index <index.json> --index-sha256 <printed-sha> --store <store>`
and set Core `AIC1_RETRIEVAL_INDEX_SHA256` to that digest. Do not enable fixture
flags for real use. Changes require a new frozen index/version, never overwrite.

## Reproducible smoke and reports

This command starts an ephemeral AIC server and the actual Core client in its
own interpreter, then stops the server. Only newly generated synthetic fixture
text is registered; no real approvals/rights/operational services are touched.
Choose a **new** output directory on each run:

```powershell
.venv/Scripts/python.exe -B tools/smoke_inference.py --head data/inference/converted-head-v1/head.json --head-sha256 a13cab03e3304a2966a5821115ec127078652cf54273e0c554e72cccbee330cd --encoder $encoder --revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 --core C:/Users/barbe/Desktop/projects/argus-core --output data/inference/real-smoke-v2
```

Actual first real-model smoke (`data/inference/real-smoke-v1/smoke-report.json`):
3 attempts: 2 successful classifications of one synthetic revision (raw/reference)
and 1 successful retrieval with one visibly synthetic source. Human-comparable=0,
Ollama-comparable=0, calibrated=false, empirical_deployment_accuracy=null. The
provided synthetic topic observation was deliberately marked incomparable, not
treated as a live Ollama assessment. No Ollama call was made.

Read-only report from Core:

```powershell
Set-Location C:/Users/barbe/Desktop/projects/argus-core
$env:PYTHONPATH='backend'
.venv/Scripts/python.exe -B -m app.services.aic_shadow --report C:/Users/barbe/Desktop/projects/argus-intelligence-models/data/inference/real-smoke-v1/core-shadow.sqlite3
```

Caller-provided Ollama observations are recorded as authenticated application
supplied and unverified. Comparison additionally requires exact content hash,
`global_defense_v1` scope and an explicitly pinned equivalent Ollama policy hash
(`AIC1_OLLAMA_POLICY_SHA256`). No such real equivalence was approved here.
Human comparisons require a matching current Phase 2M approval, same exact
registered revision/provenance, current global policy/taxonomy, and Core's pinned
`AIC1_GLOBAL_POLICY_SHA256`. Raw text, fixtures, topic labels, missing gold and
stale/policy-incompatible labels remain unavailable. Calls are not independent
gold examples; repeat requests do not expand the dataset.

## Historical Ollama false-negative: next diagnostic

Read-only audit verified Argus's
`docs/validation/phase-7h/model-evaluation/PHASE_7H4F12_MANDATORY_SUBJECT_ROOT_CAUSE_ANALYSIS.md`.
F11 case `global_scs_military`, index 0, dataset `argus_military_quality_v1`
version 1, UUID `e3a66197-9cac-4e56-b4d3-b706ab861656`, request hash
`d5018f755fa4faf697afed7052fcc432dc6445f781c4b9aa7eafe1514a5bbbff`:
Qwen2.5:3b under prompt contract 2/typed policy 1 reported mandatory military
subject `not_met`, despite the expected `met`. Geography was not required,
exclusion not matched and material connection true. The accepted topic output
was `unrelated`, reported confidence .95 (uncalibrated). The original diagnostic
used a 456-character synthetic article. The root cause remains unresolved;
synthetic framing and rubric-commentary counterfactuals did not establish a fix.

Next, preserve exact original text/request/prompt/model-policy traces and each
counterfactual independently; verify permitted local processing and exact content
revision; obtain independent global article-level human adjudication through the
existing review workflow; explicitly establish whether the old policy target
can be compared at all. Only then collect paired runs with pinned Ollama runtime
identity and this AIC head/encoder. Count denominators, abstentions and repeated
content separately. Do not reinterpret the old topic `unrelated` as nondefense,
alter operational rules or claim that a different experimental score fixes it.

## Tests, preservation and commit boundary

See `PHASE3C_RESULTS.md` for final exact suite counts, integrity checks and files.
New tests use synthetic/disposable fixtures, fake models for deterministic unit
tests, plus a real HTTP Core-client contract test. The real cached encoder smoke
is an explicit operator command rather than a mandatory model-dependent test.

No files were staged/committed. Suggested separate review boundaries are AIC
service/contracts/tests/docs and Core disabled adapter/tests/docs. Exclude all
`data/inference/`, model caches, conversion build context/wheels, fixture state,
tokens, user experiments and synthetic training datasets unless separately
reviewed/authorized. Roll back source additions/settings/router inclusion only;
do not delete historical annotations, provenance, original head or unrelated work.
