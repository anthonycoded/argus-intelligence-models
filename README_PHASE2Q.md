# Phase 2Q: local AIC-1 Review Dashboard

Open **http://127.0.0.1:6910** and sign in with your Argilla account in workspace
`aic1`. The dashboard is running locally after this implementation. Existing Argilla
remains at http://127.0.0.1:6900. No production article was edited, staged or approved
while implementing/testing the dashboard. The verified production queue contains
**24 candidates, 2 global approvals and 0 eligible records**.

## Architecture audit and authority boundaries

The pre-flight read the actual Phase 2M/N/P workflows, content reference schema,
global taxonomy/policy validator, Argilla bridge and evidence helpers. Baseline:
**463 passed, 1 skipped in 119.78 seconds**. Git was clean at the start. A private
SHA-256 snapshot captured **194 existing protected files**, including both global
approvals, every existing source/reference/provenance, Argilla response and export,
legacy Taiwan artifacts, taxonomy/policy and training guards.

The implementation reuses Python functions directly, without subprocess-calling
CLI entrypoints:

- `src/review_dashboard.py`: loopback FastAPI application, authenticated sessions,
  CSRF/origin checks and static React assets.
- `src/review_dashboard_service.py`: orchestration over `argilla_bridge.attach`,
  content bindings, `validate_article`, `create_draft`, `load_draft`, `approve`,
  immutable history and independent eligibility reporting.
- `dashboard/src/main.tsx`: React/TypeScript queue, source intake, article/event
  form, browser text selections, staging inspection and explicit approval.
- `data/review_dashboard/`: new append-only working versions, evidence receipts,
  staging receipts and process lock. This directory and built assets are ignored.

Phase 2M remains authoritative. Existing annotation envelopes, provenance, approval
history, source bytes, rights decisions and schemas were not migrated or rewritten.
Argilla and CLI entrypoints remain functional. The dashboard has its own incomplete
working snapshots because incomplete forms cannot be valid Phase 2M drafts.
Dashboard working versions are not training inputs or approvals.

Dashboard source intake uses the same immutable content registration/bridge and
optionally syncs **metadata only** to Argilla using the configured local service
API key. A sync outage retains the exact source safely and displays a retry message.
Dashboard annotation edits do not overwrite existing Argilla human responses; they
remain available in the history panel. No import silently reinterprets an old label,
repairs a quote or assigns a new evidence target.

## Windows 11 setup and one-command startup

Use Python 3.12, Docker Desktop's existing Linux-container Argilla stack and Node
20.14 or newer. The current local Node 20.14 build was verified. React/TypeScript
and esbuild are pinned with `dashboard/package-lock.json`; no hosted scripts,
fonts or browser APIs are used. No GPU or model weights are needed.

From the repository root:

```powershell
# Runtime overlay in the existing isolated Argilla environment.
.\.venv-argilla\Scripts\python.exe -m pip install -r requirements-dashboard.txt
Push-Location dashboard
npm.cmd ci --no-audit --no-fund
npm.cmd run build
Pop-Location
# Starts only AIC-1's Argilla Compose project, then the dashboard in the foreground.
./deploy/Start-Review.ps1
```

Use `./deploy/Start-Review.ps1 -SkipArgilla` if the local Argilla stack is already
healthy. `-Port 6911` selects another unprivileged loopback port; the API origin
checks follow that port. Do not run two dashboard processes against the same
dashboard root. The supported launcher holds a single-process writer lock.

The implementation run started a background dashboard at port 6910. Reuse it;
do not start another copy while that listener exists. A normally launched foreground
instance stops with Ctrl+C and releases its lock. To stop a background instance,
identify its owning process with `Get-NetTCPConnection -State Listen -LocalPort 6910`
and verify its command line is `src.review_dashboard` before stopping that process.
Do not stop unrelated Python processes or other Compose projects.

Authentication uses the installed Argilla 2.8 `/api/v1/token` form endpoint and
`/api/v1/me` plus `/api/v1/me/workspaces` permission checks. Use your actual human
account; the bootstrap account's private password is in `deploy/argilla/.env` if
that is your assigned account. No credential is embedded in React or returned to
the browser. The existing helper loads a service key only for metadata sync.

## GUI workflow: no routine CLI or JSON

1. **Queue:** search/filter candidates, see real approval/eligibility counts and
   per-source rights blockers, then select an item. Previously approved items open
   read-only. Existing Argilla drafts remain historical evidence of human work;
   they are not silently promoted into dashboard decisions.
2. **Intake:** open the publisher link independently. Paste only a legitimately
   retained neutral summary you actually wrote or an authorized excerpt. Choose
   the true representation type and document its handling basis. Keep classification
   rationale out of source summaries to reduce future target-label leakage.
   Click **Attach content**. There is no automatic article-body retrieval or AI
   summary generation. Rights remain unverified unless independently reviewed.
3. **Claims:** select article domains and defense categories, write the rationale,
   and choose scope. `other` is exclusive. Defense requires a category; nondefense
   uses an empty category selection. Dates/locations stay blank when unknown.
   Countries, roles and organizations are explicit controls, never inferred from
   a publisher or title.
4. **Scope:** choose article-level/not_enumerated, partial or complete; inline
   definitions explain the distinction. Optional event forms capture their own
   labels, countries/roles, organizations, dates, status and rationale. Event IDs
   are internal article-local identifiers. The reviewer creates an instance by
   explicitly clicking Add event; the service never extracts or invents events.
5. **Evidence:** select exact registered text, choose one or more supported claims,
   supply attribution, then click **Add supporting selection**. The server converts
   UTF-16 browser positions to Unicode character offsets, verifies the selected
   quote and binds the exact content hash. It records an evidence-selection receipt
   against the target **and its value**. Changing a domain, country, role or date
   cannot silently reuse a highlight for a different claim.
6. **Save Draft:** retain incomplete work as a new immutable working version.
   Validation errors do not discard the saved version. Save changes before leaving
   the article; unsaved browser edits are not a durable record.
7. **Validate:** all eight Details fields are generated from the controls. There
   is no required JSON editing, offset counting, clipboard operation, export,
   reconciliation or submission-ID handling. Missing source support and invalid
   scope/entity/event combinations are rejected by the existing validators.
8. **Submit:** create a Phase 2M immutable draft. It is not an approval. Repeating
   submission of the same working version returns the same staged receipt. Staging
   is resumable after a browser refresh.
9. **Inspect Staged Draft:** inspect rendered labels, fields, exact quotes, source
   hash and retained text. Approval remains disabled until an explicit human
   confirmation checkbox is selected. The final request binds the authenticated
   account to a short-lived inspection ticket for that exact working version,
   immutable draft and source. Any changed work/source makes the ticket stale.
10. **Approve:** appends the existing Phase 2M approval envelope as the authenticated
    reviewer. This does not alter rights. **Next article** navigates to the next
    queue item without copying annotations or asking for an ID.

For an approved article or a new source revision of it, explicitly click **Start
amendment**. The core requires the current approval head as supersession parent;
old approvals remain intact. Re-select evidence before submitting amended claims.

## History, eligibility and source identity

The Audit / history panel includes source representations, historical text,
immutable approvals with current/superseded markers, dashboard working versions,
legacy Argilla draft/submitted responses, and quality advisories. Historical text
and responses are read-only. Approval counts use Phase 2M current family heads;
queue approval status also requires the approved source to match the current
content representation. These are intentionally distinct from source rights.

Per-source eligibility blockers come from `global_review.eligibility_report`, not
UI guesses. No dashboard endpoint clears or changes rights. Unverified, restricted,
conflicting or missing decisions remain blocked. No classifier trainer or model
inference is introduced. Existing frozen dataset and legacy training safeguards
are unchanged.

## Security and failure handling

- Only loopback binding is supported. The server rejects non-loopback peers and
  unexpected Host values; forwarded headers are not trusted. HTTP is local-only.
- Password authentication and role/workspace access are checked against Argilla.
  Permissions are rechecked on authenticated API requests, including approval.
  A stopped Argilla service, expired token or removed access fails closed.
- Session identifiers are random, HttpOnly, SameSite=Strict cookies. Sessions are
  memory-only and expire after eight hours. Writes require same Origin, JSON and
  a session-bound CSRF token. Login has a bounded attempt rate.
- API docs/debug endpoints are disabled. Source text is rendered as text, never
  HTML; assets are local with a restrictive CSP and no external connections.
- Bodies are bounded to 3 MiB; retained source representations to 2 MiB. Browser
  input never becomes a filesystem path. IDs resolve only through validated stores.
- Immutable receipts and optimistic working versions reject stale saves, wrong
  actors, changed claims, forged evidence and source/contract drift. Partial sync
  failures retain content and expose a retry action without inferring success.
- UI errors do not expose tracebacks, credentials or server filesystem exceptions.
  No access/body logging is enabled. Private server logs stay under ignored data.

This preserves the existing **single-writer local filesystem trust model**. Do not
perform concurrent mutations through dashboard, Argilla bridge CLI and manual
filesystem edits. The dashboard serializes its own writes and core guards reject
stale/forked approvals, but legacy CLI tools do not share its process lock. This
is not an internet-facing multi-tenant or tamper-proof WORM deployment. A user with
full OS/store control can replace artifacts; hashes cannot authenticate that actor.

## Tests and browser evidence

Ordinary API/unit tests use synthetic temporary stores and an injected fixture
authenticator; production authentication has no such request-configurable bypass.
No test uses the two approved production articles.

```powershell
# Test overlay in the existing research environment.
.\.venv\Scripts\python.exe -m pip install -r requirements-dashboard-test.txt
$env:PLAYWRIGHT_SKIP_BROWSER_GC='1'
.\.venv\Scripts\python.exe -m playwright install chromium
$env:AIC_DASHBOARD_BROWSER='1'
$env:AIC_BROWSER_EVIDENCE='data/review_dashboard/browser-evidence'
.\.venv\Scripts\python.exe -B -m pytest tests/test_review_dashboard.py tests/test_review_dashboard_browser.py -q
# Entire suite, including the same disposable Chromium workflow:
.\.venv\Scripts\python.exe -B -m pytest -q
Remove-Item Env:AIC_DASHBOARD_BROWSER
```

The focused dashboard suite passed **20 tests in 19.45 seconds**. The real browser
workflow exercised login, metadata-only intake, exact Unicode text selection,
eight-field generation, saved draft/editing, missing-evidence error recovery,
validation, stage inspection, disabled approval before confirmation, synthetic
approval, rights blocking, history and next-item navigation. API coverage includes
CSRF/origin/Host/auth, revoked permissions, wrong evidence actor, changed claims,
source/work staleness, amendments, duplicate operations and sync outage recovery.

Final full suite with Chromium enabled: **483 passed, 1 skipped, 1 warning in
233.96 seconds**. This preserves the 463-test baseline and adds 19 API/integration
cases plus the real browser workflow. The skipped test is the prior optional
Argilla Docker smoke. The warning is Starlette's upstream deprecation of its httpx
test-client adapter; runtime Argilla/httpx compatibility was retained.

Screenshots contain disposable synthetic data, **not production approvals**:

- `data/review_dashboard/browser-evidence/01-validated-form.png`
- `data/review_dashboard/browser-evidence/02-staged-inspection.png`
- `data/review_dashboard/browser-evidence/03-approved-rights-blocked.png`

The live instance was checked read-only for login, disabled docs, loopback binding,
24 candidates, 2 approvals and 0 eligible records. All 194 pre-existing protected
files retained their original hashes. No production approval or rights action was
performed, no model was trained, no Argus repositories/services were changed, and
no Git commit was made.
