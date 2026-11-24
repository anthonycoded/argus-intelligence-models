# Explicit UTF-8 decoding is required on Windows PowerShell 5.1 as well as pwsh.
# This only copies a prepared local form; it never writes Argilla or approves.
param([Parameter(Mandatory = $true)][string]$ContentPath)
$resolvedDetails = (Resolve-Path -LiteralPath $ContentPath -ErrorAction Stop).Path
$strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
$detailsText = [System.IO.File]::ReadAllText($resolvedDetails, $strictUtf8)
if ([string]::IsNullOrWhiteSpace($detailsText)) { throw 'Details file is empty' }
$null = ConvertFrom-Json -InputObject $detailsText -ErrorAction Stop
Set-Clipboard -Value $detailsText -ErrorAction Stop
Write-Output 'Prepared details copied as Unicode. Inspect and paste in Argilla; no response was written or approved.'
