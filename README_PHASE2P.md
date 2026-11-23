# Phase 2P: self-hosted Argilla review

Argilla is a local review interface and staging source. Phase 2M remains the only
global approval authority; Phase 2L/2N training, rights and dataset checks are
unchanged. No real annotation is automatically submitted, reviewed or approved.

## Verified deployment and compatibility

The integration targets **Argilla SDK/server 2.8.0**, not the incompatible 1.x API.
The Docker images are pinned by version and immutable registry digest in
`deploy/argilla/compose.yaml`. Elasticsearch 8.17.0, PostgreSQL 14.17 and Redis
7.4.2 are separate AIC-1 services with persistent named volumes. The Argilla worker
uses the same server image and one worker process.

Official references checked before implementation:

- [Argilla 2.8 deployment example](https://github.com/argilla-io/argilla/blob/v2.8.0/examples/deployments/docker/docker-compose.yaml)
- [Server settings and supported telemetry opt-out](https://docs.argilla.io/latest/reference/argilla-server/configuration/)
- [Native annotation questions](https://docs.argilla.io/latest/reference/argilla/settings/questions/)
- [Responses, reviewer IDs and draft/submitted statuses](https://docs.argilla.io/latest/reference/argilla/records/responses/)
- [Windows Docker Desktop requirements](https://docs.docker.com/desktop/setup/install/windows-install/)

On this workstation Docker Engine 29.9.2 and Compose 5.6.1 were available.
The existing Argus PostgreSQL/Redis and Studio AI containers were inspected for
port conflicts only. They were not stopped, reconfigured or modified.

Use Docker Desktop with **Linux containers**, WSL 2 and hardware virtualization.
Docker documents 8 GB system RAM as a Windows minimum. As a project planning
estimate, allow 4 CPU cores and 4–6 GB available Docker memory, with 16 GB host RAM
preferred when the other Argus services are also running. No GPU is needed.
Allow several GB of disk space for images, volumes and backups. Initial image
downloads and database/search startup can take several minutes.

The running idle pilot used approximately 1.55 GiB across the five containers in
the observed Docker stats snapshot (about 206 MiB server, 210 MiB worker, 1.12 GiB
search, 27 MiB PostgreSQL and 6 MiB Redis). This is an idle measurement, not a
capacity guarantee for larger annotation datasets.

Only `127.0.0.1:6900` is published. Search, PostgreSQL and Redis have **no host
ports**. A private internal network connects backends; only the Argilla server also
joins the web bridge needed for Docker's loopback port publishing. The SDK rejects
non-loopback URLs, proxies inherited from the environment, and HTTP redirects.
This is a workstation deployment, not an internet-facing or hostile multi-user service.

Supported telemetry controls `HF_HUB_DISABLE_TELEMETRY=1` and `HF_HUB_OFFLINE=1`
are set for server, worker and SDK sessions. Progress sharing is disabled. The old
`ARGILLA_ENABLE_TELEMETRY` setting is deprecated in the verified image and is not
used. There is no Spaces deployment, hosted AI integration, webhook, embedding
upload, model download or classifier training.

## Install and start on Windows

Run PowerShell from the repository root. Keep the SDK in its own environment:

```powershell
py -3.12 -m venv .venv-argilla
.\.venv-argilla\Scripts\python.exe -m pip install -r requirements-argilla.txt -c constraints-argilla-win-py312.txt
```

The constraint file records the verified Windows/Python 3.12 SDK environment.
`requests` is explicit because the 2.8 SDK imports it without declaring it directly.
The training environment and its dependency declarations remain unchanged.

For a fresh workstation, copy `deploy/argilla/.env.example` to `.env` in the same
directory and fill **every** blank secret with independent random values. Compose
refuses to start while these required secret values are empty.
Use URL-safe hexadecimal for the database password because it is embedded in its
connection URL. Do not overwrite an existing `.env`. This implementation run already
created random local secrets there; retrieve the browser password from that local
file without pasting it into chat, Git, scripts or logs.

```powershell
docker compose --env-file deploy/argilla/.env -f deploy/argilla/compose.yaml config --quiet
docker compose --env-file deploy/argilla/.env -f deploy/argilla/compose.yaml up -d --wait --wait-timeout 300
docker compose --env-file deploy/argilla/.env -f deploy/argilla/compose.yaml ps
. ./deploy/argilla/Use-LocalArgilla.ps1
```

The helper sets process-local SDK variables without printing credentials. Open
**http://127.0.0.1:6900**, log in as `AIC_ARGILLA_USERNAME` with the local password,
and select workspace `aic1`. Changing bootstrap password/API-key environment values
does not rotate an existing database user; use Argilla's user management to rotate
credentials and update `.env` consistently.

## Dataset setup and idempotent queue import

```powershell
. ./deploy/argilla/Use-LocalArgilla.ps1
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge init --sample data/discovery/phase2o_001/sample
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge setup
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge import
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge reconcile
```

The actual dataset is `aic-global-v2-2c8eac532566`. Its suffix binds the versioned
adapter contract, taxonomy v2 and policy. Existing incompatible settings are rejected.
The real 24-candidate import succeeded; repeating it added zero records. All 24 are
**pending content**, with zero responses/approvals created by this import.

Local bridge root defaults to `data/argilla`; alternate roots use `--root PATH`
**before** the subcommand. All generated bridge data and credentials are ignored
by Git. The bridge binds the immutable Phase 2O sample and exact candidate metadata,
sampling identifiers and discovery-ranking revision data. Each content version gets
a distinct external record ID; the original candidate ID is retained in metadata
and visible context. Record fields cannot be silently updated through sync.

Article title, safe source URL, publisher, publication/collection times, content
revision and source/provenance binding are visible. Origin and query hints are not
verified event geography or labels. No machine suggestions are placed in response
controls, and no default domains/events are assigned.

## First article: browser draft

1. Open the dataset and search for **Human Settlements seeks to speed up housing
   projects**, or filter `candidate_id` to
   `candidate-04d4ab486c99ea5a3bcdb025058db8077ff2f86d6a9ad94bfed7357d1baaf5aa`.
2. Inspect title, source URL, publisher and the pending-content notice. Visit the
   publisher independently under its access conditions.
3. If your assessment supports it, select **economics** and select **none** under
   defense event types. These are your draft choices, not established ground truth.
4. Save as a **draft**. Required unanswered questions may remain incomplete in a
   draft. The UI displays one record at a time and its annotation progress counters.
5. Before submission/staging, attach an independently supplied, permitted content
   representation and complete the evidence and supplemental form below.

The existing `review/001/content.txt` was nonempty when this phase began. It and
all review packet files were preserved byte-for-byte. File presence does not attest
authorship or permission, so its text was **not automatically uploaded or registered**.
An actual human must determine its representation type and handling basis.

## Explicit content attachment and revisions

Only after checking the exact text and its handling basis, replace the handling
statement below and choose the correct content type. `human_summary` asserts actual
human authorship; do not use it for an AI-generated summary. Other permitted
representation types are documented in Phase 2M.

```powershell
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge attach --candidate-id candidate-04d4ab486c99ea5a3bcdb025058db8077ff2f86d6a9ad94bfed7357d1baaf5aa --text-file data/discovery/phase2o_001/review/001/content.txt --content-type permitted_excerpt --rights-note 'REPLACE with actual permission/handling basis; training rights unverified'
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge import
```

Attachment uses Phase 2N intake and Phase 2M source registration. Exact bytes,
canonical source identity, normalized duplicate fingerprint, publisher metadata,
provenance and sample bindings are retained. Empty or invalid text is rejected.
Reattaching identical text with the same handling assertion is idempotent. Different
text creates a new source revision and Argilla record; existing representations,
responses and approvals remain historical. Existing representations with mismatched
handling assertions are rejected, rather than rewritten.

Use the newly returned record/content revision for review; historical records remain
visible in Argilla. Responses targeting an older representation cannot be staged.
Do not transfer labels/evidence mechanically to a changed representation. Training
rights remain unverified unless a separate explicit rights review determines otherwise.

## Two-stage article and event annotation

Native controls capture multi-label domains, multi-label defense event categories,
rationale, event coverage and optional evidence highlights. `none` is an adapter-only
explicit choice for no defense events and maps to an empty event-type list.
It cannot coexist with categories. The Phase 2M validator enforces `other`
exclusivity, defense/category consistency and all taxonomy rules.

Argilla's native questions do not represent the full nested Phase 2M schema. The
**details** text question is therefore a strict supplemental JSON form. Start with
`examples/argilla_details_TEMPLATE.json` and fill its eight fields in the browser:

- `countries`: ISO alpha-2 country/role objects; roles come from taxonomy v2.
- `organizations`: exact organization names supported by this representation.
- `event_date`, `event_location`: null when unknown; dates use strict YYYY-MM-DD.
- `evidence_status`: reported, disputed or unknown; never inferred corroboration.
- `event_coverage_note`: explain article-only, partial or complete enumeration.
- `events`: article-local event objects using the Phase 2M schema; empty for
  `not_enumerated`. Article aggregate labels remain independent of event instances.
- `evidence`: target paths, exact content hash, Unicode offsets, verbatim quotes
  and source attribution, as documented in README_PHASE2M.md.

No absent required field is invented by the adapter. Evidence must cover each
asserted domain/entity/date/location/status and event claim. Highlighting alone
does not identify which claim a span supports: supplemental evidence remains
authoritative. Optional native spans must match validated supplemental offsets.
Browser offsets differing on astral Unicode or line endings must be corrected to
Python Unicode offsets against the exact registered text; mismatches are rejected.

Full policy and event-category inclusion/exclusion definitions appear in the record's
guidance field and dataset guidelines. Save incomplete work as draft, then submit
only when both stages have been checked. A submitted response is still unapproved.

## Export, validation, review and explicit approval

```powershell
. ./deploy/argilla/Use-LocalArgilla.ps1
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge export
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge reconcile
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge stage SUBMISSION_ID
```

Export creates append-only submission snapshots in `data/argilla/submissions` and
an export membership/history chain. Draft/discarded responses are retained for
reconciliation but never become Phase 2M drafts. Repeating synchronization is
idempotent. Replaced/withdrawn responses from a newer successful export are stale.
Unknown users, mixed statuses, duplicate answers and changed record bindings reject
export. Stale content, missing content, taxonomy/policy drift, malformed JSON,
forged evidence and unsupported labels reject staging.

`stage` creates an immutable **validated draft**, not an approval. Inspect the
returned draft and exact source text first:

```powershell
.\.venv-argilla\Scripts\python.exe -B -m src.global_review review DRAFT_ID
# Only the actual response author, after checking the displayed draft and content:
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge review SUBMISSION_ID --reviewer ARGILLA_USER_UUID --confirm-review
# Only after the actual human approval decision:
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge approve REVIEW_ID --reviewer ARGILLA_USER_UUID --confirm-human-review
.\.venv-argilla\Scripts\python.exe -B -m src.argilla_bridge reconcile
```

Use the UUID from the exported response, not a display-name guess. The approval
identity records `argilla:UUID:username`. The bridge requires the same author for
review and approval; an adjudicator must submit their own reviewed response rather
than impersonating another author. Phase 2M's CLI confirmation is an attestation,
not cryptographic login authentication.

For a correction to an existing approval use `stage ... --supersedes APPROVAL_ID`
and `review ... --supersedes APPROVAL_ID`, then explicit approval. Phase 2M rejects
duplicate roots, forks and stale parents. Previous approvals are never overwritten.
Reconciliation reports Argilla draft/submitted/discarded versus AIC-1 unstaged,
validated_draft, reviewed and approved, plus separate eligibility/rights blocks.

Approval never clears rights. Global export remains the separate Phase 2N operation;
Argilla responses and staging files are not accepted by the legacy trainer. Export
current responses before reviewing/approving and stop if synchronization fails.
Offline approval checks the last successful local export, not live server state.

## Shutdown, backup and recovery

Stop only this project; named volumes remain intact:

```powershell
docker compose --env-file deploy/argilla/.env -f deploy/argilla/compose.yaml stop
# Resume:
docker compose --env-file deploy/argilla/.env -f deploy/argilla/compose.yaml up -d --wait
```

For a consistent cold backup, stop this project first. Archive all four named
volumes (`aic1-annotation_home`, `_database`, `_search`, `_queue`) together, plus
`data/argilla`, `data/global_annotations`, the bound Phase 2O sample/ranking/feed
bundles, pinned Compose/constraints files and the private `.env`. Keep backups
private and outside Git; Docker startup logs can also contain the bootstrap API key.
Do not paste unredacted logs into tickets.

Example volume archives using the already installed server image, with no network:

```powershell
$backup = Join-Path (Get-Location) ('data/backups/argilla-' + (Get-Date -Format yyyyMMdd-HHmmss))
New-Item -ItemType Directory -Path $backup -ErrorAction Stop | Out-Null
foreach ($volume in @('home','database','search','queue')) {
  docker run --rm --network none --entrypoint python --mount "type=volume,source=aic1-annotation_$volume,target=/source,readonly" --mount "type=bind,source=$backup,target=/backup" argilla/argilla-server:v2.8.0@sha256:6f4af8fcf4b809d25aa88a6a4f8838dbacab9296c83b055a9a58f1db7526431a -c "import tarfile; t=tarfile.open('/backup/$volume.tar','w'); t.add('/source',arcname='data'); t.close()"
  if ($LASTEXITCODE -ne 0) { throw 'Backup failed; keep the stack stopped and investigate' }
}
```

Copy the local directories/credentials listed above into that same protected backup
using `Copy-Item -LiteralPath` before resuming. Hash the backup files and verify the
hashes before recovery. Do not use `down -v`, prune volumes, or restore over live data.

For recovery, preserve the original project and restore to **new empty volumes**:

1. Set a different localhost port in a private recovery env file. Use
   `docker compose -p aic1-annotation-restore --env-file RECOVERY_ENV -f deploy/argilla/compose.yaml create`
   to create stopped recovery containers/volumes with the same pinned images.
2. Restore each archive into its corresponding `aic1-annotation-restore_*` volume
   using a temporary offline container. Check the destination is empty before
   extracting; never merge with a pre-existing database. Archives created above have
   a `data/` prefix: extract to a temporary directory using Python's
   `tarfile.extractall(..., filter='data')`, then copy the contents of `data/`
   into the empty mounted destination, preserving ownership and permissions.
3. Restore local bridge/source/sample artifacts to their original absolute paths
   or a separate workstation retaining those paths. The bridge context deliberately
   binds absolute paths; do not edit immutable JSON to relocate it.
4. Start only the recovery project with `up -d --wait`, point the SDK at its new
   loopback port, run `setup`, `export`, and `reconcile`, and compare expected IDs,
   approvals, source hashes and rights. Keep the original backup until verified.

The live startup/import and SDK smoke were tested; a destructive restore rehearsal
was not performed in this phase.

## Tests, troubleshooting and limits

The baseline suite passed **362 tests in 95.20 seconds**. New ordinary tests are
offline and use mocked SDK resources plus a real synthetic Phase 2N intake path.
The opt-in Docker smoke creates and removes only a uniquely named synthetic dataset;
its machine-generated draft responses never touch real candidates or approvals:

```powershell
. ./deploy/argilla/Use-LocalArgilla.ps1
.\.venv-argilla\Scripts\python.exe -m pip install 'pytest>=8,<10'
$env:AIC_ARGILLA_SMOKE='1'
.\.venv-argilla\Scripts\python.exe -B -m pytest tests/test_argilla_local_smoke.py -q
Remove-Item Env:AIC_ARGILLA_SMOKE
# Ordinary suite in the original research environment; no Docker/network required:
.\.venv\Scripts\python.exe -B -m pytest -q
```

The local smoke passed, including economics/none draft round-trip and reviewer UUID
attribution; upstream SDK `datetime.utcnow` deprecation warnings remain.

Final ordinary suite: **400 passed, 1 skipped in 217.46 seconds** (362 existing
tests plus 38 new offline cases; the skipped case is the explicit Docker smoke).
Separate local smoke: **1 passed in 8.49 seconds**, with 19 upstream SDK deprecation
warnings. All 118 pre-flight protected files remained byte-for-byte unchanged,
including the five legacy approvals, existing sidecars, review packet edits and
Phase 2L/2M/2N guards. The blank-secret Compose template was verified to fail before
startup. A machine-readable local result is `data/argilla/phase2p_report.json`.

If Docker says access denied, use a normal Docker-enabled user terminal; do not
change other projects or disable Docker security. If port 6900 is occupied, select
a free `AIC_ARGILLA_PORT` and reload the helper. The health endpoint is `/api/status`
(not `/api/v1/status`). If image pulls fail, leave the offline suite usable and
report the deployment limitation. If Elasticsearch fails, check Docker RAM, disk
space and its logs without exposing credentials; do not publish its port.

This is a single-writer local research integration. Filesystem hashes detect local
tampering but do not authenticate an attacker controlling the entire store or Docker
daemon. Browser/native highlights are supplemental; semantic entailment still needs
a human. Nested events require the documented supplemental JSON step. Old Argilla
representations remain visible and must not be mistaken for the current revision.
No real body text, human response, rights clearance or model training was generated.

Use one bridge/sample per dataset workspace. The dataset name binds the annotation
contract, not a batch ID; a different sample must use a separate Argilla workspace
(`--workspace` on setup/import/export) and bridge root. Cross-batch aggregation is
not implemented, and unknown remote records cause export to fail closed.
