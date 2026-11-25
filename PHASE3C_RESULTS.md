# Phase 3C verification results

Verified November 25, 2026. No commit, push, merge, production enablement,
training, model download, human approval or rights change was performed.
Architecture, commands, API details and diagnostic next steps: [PHASE3C.md](PHASE3C.md).

## Tests

| Check | Actual result |
| --- | --- |
| AIC-1 preflight, including opt-in browser tests | 538 passed, 1 skipped |
| AIC-1 focused new service/conversion/real HTTP tests | 28 passed |
| AIC-1 final full suite, browser tests enabled | **566 passed, 1 skipped**, 287.75 s |
| Core preflight with disposable services | 849 passed |
| Core new focused shadow tests | 32 passed |
| Core final full safe harness with disposable services | **881 passed, 0 skipped**, 177.76 s |
| Real cached encoder + numeric head + Core HTTP smoke | 2 classifications + 1 retrieval succeeded |
| Isolated original-head/numeric parity | 19 vectors, identical predictions, maximum probability error 1.11e-16 |
| Protected-artifact hashes | 253 checked, **0 changed or missing** |

The AIC skip is the separately opt-in live Argilla Docker smoke
(`AIC_ARGILLA_SMOKE` was not enabled). Browser persistence/review tests ran.
Both repositories retain an existing Starlette/httpx deprecation warning.
An initial unprivileged focused run encountered Windows temp/cache ACL limits;
fresh disposable temp paths and the authorized test identity resolved them.
No ACLs were reset. An initial Core offline-only baseline had 734 passes,
105 skips and 10 failures from absent database/Redis fixtures; rerunning through
the established disposable-services harness passed all 849 baseline tests.
These are environment limitations, not suppressed new test failures.
Argus was inspected read-only and unchanged, so its suite was not rerun.

Final full commands (PowerShell, respective repository roots):

```powershell
$env:AIC_DASHBOARD_BROWSER='1'
.venv/Scripts/python.exe -B -m pytest -q --tb=short -p no:cacheprovider --basetemp "$env:TEMP/aic3c-full-$([guid]::NewGuid())"
```

```powershell
.venv/Scripts/python.exe -B backend/tests/phase_7h4b_runner.py --services -q --tb=short
```

The Core harness disabled production dotenv/operator AIC settings, blocked
unexpected network access, created only disposable task-owned PostgreSQL/Redis
containers and network, and removed them afterward. Default OpenAPI and normal
Ollama response tests passed. The first interrupted test scratch path was
confirmed absent at final cleanup.

## Model and smoke evidence

The original joblib was verified at the expected local training output path and
matched the specifically authorized SHA-256. The only deserialization occurred
inside the inspected unprivileged, read-only, network-disabled disposable
container. The host converter is disabled. The exact worker container and the
task-owned converter image were removed afterward; unrelated images/services
and the cached public base image were preserved.

Numeric head: `a13cab03e3304a2966a5821115ec127078652cf54273e0c554e72cccbee330cd`.
The original head is unchanged:
`3ff5a564931b6db164f4fa64810d30ba6d632f46942410d425f30c0037fd6bb5`.
Fixed-vector probability tolerance was 1e-10; actual maximum difference was
1.1102230246251565e-16 with zero threshold ties. This is numerical test evidence,
not real-world classifier accuracy or historical training-lineage proof.

Retained **ignored local artifacts**, excluded from staging:

- `data/inference/converted-head-v1/head.json`
- `data/inference/converted-head-v1/trust-manifest.json`: source/output hashes,
  operator attestation, training-script hash, controller/worker hashes, pinned
  encoder, public wheel/build provenance, isolation settings and parity evidence.
- `data/inference/conversion-build-6096475998f543159b05567ca5bc1113/build-evidence.json`
  and the task-owned public wheels/build context (no production data).
- `data/inference/real-smoke-v1/smoke-report.json` and disposable fixture index/store
  and metadata-only service/Core journals.
- `data/inference/final-integrity.json`: aggregate preservation/count evidence.

The real-model smoke used local safetensors MiniLM revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, encoder tree hash
`cdf609f5ee2eeb7204517d51b88b8079fb53624531a28ee74c524b58acf36caa`.
The actual Core client ran in its own interpreter against an ephemeral loopback
AIC HTTP server. Raw-text and registered-reference classification both worked;
retrieval returned one explicitly synthetic permitted source. The server stopped
after the smoke. No production Core instance or Ollama provider was invoked.

Report denominators: 3 attempts, 2 successful classifications, 1 distinct content
revision, 1 retrieval, **0 comparable human labels**, **0 comparable Ollama
assessments**. The supplied synthetic topic observation was correctly excluded.
Empirical deployment accuracy remains null and probabilities uncalibrated.

## Preservation and real dataset readiness

All 253 files in the preflight protection snapshot match byte-for-byte, including
the five legacy Taiwan approvals/sidecars, global approval history/provenance,
representation and rights records, taxonomies/policies, original experimental
head/scripts/dataset/splits and Phase 2L training guards. No legacy labels were
reinterpreted, approvals executed or rights inferred.

The authoritative `data/global_annotations` store contains **4 current approvals**
and 4 registered representations; all 4 rights statuses are **unverified**;
approval-store validation succeeds and future-dataset eligibility is **0**.
Counts were rechecked with the read-authorized identity: the restricted sandbox
account cannot reliably enumerate this protected directory and its empty listing
must not be treated as the dataset state. No real-source retrieval permission was
granted. This phase establishes an experimental integration, not a rights-cleared
training dataset, calibrated classifier, or deployment-readiness claim.

## Files and Git boundaries

AIC-1: branch `main`, HEAD `e102e33`, unchanged. Modified tracked file:

- `.gitignore` (ignore inference runtime/conversion/index/journal state).

New implementation/review files:

- `requirements-inference.txt`
- `src/inference_contracts.py`
- `src/inference_runtime.py`
- `src/inference_service.py`
- `src/inference_retrieval.py`
- `src/inference_audit.py`
- `tests/test_inference_service.py`
- `tests/test_inference_conversion.py`
- `tests/test_inference_http_integration.py`
- `tools/prepare_conversion_image.py`
- `tools/head_conversion_payload.py` (container-only deserialization worker)
- `tools/convert_head_isolated.py` (host controller; never deserializes)
- `tools/smoke_inference.py`
- `examples/inference/classify-request.json`
- `examples/inference/classify-response.json`
- `examples/inference/contracts.json`
- `PHASE3C.md`, `PHASE3C_RESULTS.md`

Existing untracked user `experiments/` and `aic1_synthetic_v2/` remain untouched.
Do not include them in a blanket add. Converted models, caches, private datasets,
runtime databases and tokens are not staged.

Core: branch `architecture/separate-global-chess`, HEAD `a774b4d`, unchanged.
Modified tracked files:

- `.gitignore`
- `backend/app/core/config.py`
- `backend/app/api/v1/router.py`
- `backend/tests/phase_7h4b_runner.py` (clear experimental settings in safe harness)

New files:

- `backend/app/clients/aic1_client.py`
- `backend/app/services/aic_shadow.py`
- `backend/app/api/v1/aic_shadow.py`
- `backend/tests/test_aic_shadow.py`
- `AIC1_SHADOW.md`

Argus: branch `main`, HEAD `c93f029`, unchanged. Pre-existing modified files
remain `backend/tests/test_disposable_redis_startup.py`,
`docs/development/SOC_HOST_AUTOMATIC_STARTUP.md`,
`docs/validation/general/ARGUS_V1_4_18_9B_LIVE_PREPARATION.md`,
`scripts/windows-startup/Common.ps1`, plus the existing untracked Windows tunnel
migration tests/docs/scripts. No Argus panel or other edits were made.
Intendo remains intact per the operator's explicit instruction.

Staged file lists in both changed repositories are empty. `git diff --check`
passes (Git emits ordinary Windows LF/CRLF notices). Recommended future commit
boundaries: independently review AIC's service/contracts/tests/docs, then Core's
disabled adapter/tests/docs. No commit is authorized by this report.

## Remaining limitations

- Historical encoder/training dataset identity is not recoverable from the old
  unpinned training script; the trust manifest makes this explicit.
- Fixed probes cannot prove equality on every possible vector, calibration or
  deployment accuracy. The model was trained on synthetic data.
- Caller processing attestations and index permission documents require actual
  operator review; the software cannot decide publisher rights automatically.
- No real-source permitted index, independent human comparison cohort or live
  paired Ollama evaluation was created. Historical false-negative next steps
  are in `PHASE3C.md`; its cause remains unresolved.
- Journals are bounded append-only application stores, not administrator-proof
  WORM. Deadline expiry cannot terminate a stuck native inference thread; it
  retains admission until completion and may require operator restart.
- Runtime limits constrain input/tokens/threads/concurrency; Windows service
  RAM is not hard-capped. Dependencies are bounded declarations plus recorded
  exact conversion versions, not a complete portable inference lockfile.
- Optional Argus display was deferred. No production feature is enabled.

Stop at Phase 3C. No later training or operational automation is started.
