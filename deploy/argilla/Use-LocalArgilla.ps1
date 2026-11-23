# Run from the repository root. Sets process-local variables without printing secrets.
$credentialPath = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path -LiteralPath $credentialPath)) { throw 'Create deploy/argilla/.env first; see README_PHASE2P.md' }
$values = @{}
foreach ($line in Get-Content -LiteralPath $credentialPath) {
    if ($line -match '^([A-Z_]+)=(.*)$') { $values[$matches[1]] = $matches[2] }
}
if (-not $values['AIC_ARGILLA_API_KEY'] -or $values['AIC_ARGILLA_API_KEY'].StartsWith('CHANGE_ME')) { throw 'Set a random API key first' }
$env:ARGILLA_API_KEY = $values['AIC_ARGILLA_API_KEY']
$env:ARGILLA_API_URL = 'http://127.0.0.1:' + $values['AIC_ARGILLA_PORT']
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:HF_HUB_OFFLINE = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
