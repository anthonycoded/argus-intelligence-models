# Run from any directory. Starts only AIC-1 annotation services and dashboard.
param([int]$Port = 6910, [switch]$SkipArgilla)
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Choose an unprivileged localhost port' }
if (-not $SkipArgilla) {
    docker compose --env-file deploy/argilla/.env -f deploy/argilla/compose.yaml up -d --wait --wait-timeout 300
    if ($LASTEXITCODE -ne 0) { throw 'Argilla startup failed; no other project was changed' }
}
if (-not (Test-Path -LiteralPath 'dashboard/dist/index.html')) { throw 'Build the dashboard first: cd dashboard; npm ci; npm run build' }
. ./deploy/argilla/Use-LocalArgilla.ps1
Write-Output "AIC-1 Review: http://127.0.0.1:$Port (sign in with your Argilla account)"
& ./.venv-argilla/Scripts/python.exe -B -m src.review_dashboard --port $Port
