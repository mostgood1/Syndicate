param(
    [string]$Date,
    [string]$BaseUrl,
    [switch]$Json,
    [switch]$RefreshOdds,
    [string]$OddsPhase = 'all',
    [string]$OddsSports = 'all',
    [string]$OddsRegions = 'us',
    [switch]$SkipTests,
    [switch]$SkipSmoke,
    [switch]$SkipSourceUpdates,
    [switch]$SkipRefreshGate,
    [switch]$SkipGitPush,
    [switch]$WhatIf,
    [switch]$SkipNFL,
    [switch]$SkipNCAAF,
    [switch]$SkipNCAAB,
    [switch]$SkipMLB,
    [switch]$SkipNBA,
    [switch]$SkipNHL,
    [switch]$SkipWNBA
)

$ErrorActionPreference = 'Stop'

# Use Central Time for date calculations to match Syndicate's timezone
if ([string]::IsNullOrWhiteSpace($Date)) {
    $centralTZ = [TimeZoneInfo]::FindSystemTimeZoneById("Central Standard Time")
    $Date = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $centralTZ).ToString('yyyy-MM-dd')
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = if ($env:PYTHON_PATH) { $env:PYTHON_PATH.Split("`n")[0].Trim() } else { "python" }
$unifiedArgs = @(
    'powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'unified_daily_update.ps1'),
    '-Date', $Date
)

if ($BaseUrl) { $unifiedArgs += @('-BaseUrl', $BaseUrl) }
if ($Json) { $unifiedArgs += '-Json' }
if ($RefreshOdds) { $unifiedArgs += '-RefreshOdds' }
if ($OddsPhase) { $unifiedArgs += @('-OddsPhase', $OddsPhase) }
if ($OddsSports) { $unifiedArgs += @('-OddsSports', $OddsSports) }
if ($OddsRegions) { $unifiedArgs += @('-OddsRegions', $OddsRegions) }
if ($SkipTests) { $unifiedArgs += '-SkipTests' }
if ($SkipSmoke) { $unifiedArgs += '-SkipSmoke' }
if ($SkipGitPush) { $unifiedArgs += '-SkipGitPush' }
if ($WhatIf) { $unifiedArgs += '-DryRun' }
if ($SkipSourceUpdates) { $unifiedArgs += '-SkipSourceUpdates' }
if ($SkipRefreshGate) { $unifiedArgs += '-SkipRefreshGate' }
if ($SkipNFL) { $unifiedArgs += '-SkipNFL' }
if ($SkipNCAAF) { $unifiedArgs += '-SkipNCAAF' }
if ($SkipNCAAB) { $unifiedArgs += '-SkipNCAAB' }
if ($SkipMLB) { $unifiedArgs += '-SkipMLB' }
if ($SkipNBA) { $unifiedArgs += '-SkipNBA' }
if ($SkipNHL) { $unifiedArgs += '-SkipNHL' }
if ($SkipWNBA) { $unifiedArgs += '-SkipWNBA' }

Push-Location $repoRoot
try {
    Write-Host '==> Unified daily update' -ForegroundColor Cyan
    Write-Host ("    " + ($unifiedArgs -join ' ')) -ForegroundColor DarkGray
    & $unifiedArgs[0] $unifiedArgs[1..($unifiedArgs.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "Unified daily update failed with exit code $LASTEXITCODE"
    }

    $reconciliationArgs = @(
        $python, '-m', 'syndicate.features.prediction_reconciliation', '--date', $Date
    )
    Write-Host '==> Prediction reconciliation' -ForegroundColor Cyan
    Write-Host ("    " + ($reconciliationArgs -join ' ')) -ForegroundColor DarkGray
    & $reconciliationArgs[0] $reconciliationArgs[1..($reconciliationArgs.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "Prediction reconciliation failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}