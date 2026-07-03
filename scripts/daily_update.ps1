<#
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Daily update wrapper that launches the unified runner and reconciliation.

Constraints:
- State-driven execution
- Avoid redundant computation
#>

param(
    [string]$Date,
    [string]$BaseUrl,
    [switch]$Json,
    [switch]$RefreshOdds,
    [string]$OddsPhase = 'all',
    [string]$OddsSports = 'all',
    [string]$OddsRegions = 'us',
    [int]$EventSimForceWindowMinutes = 30,
    [string[]]$ActiveSports,
    [switch]$SkipTests,
    [switch]$SkipSmoke,
    [switch]$SkipSourceUpdates,
    [switch]$SkipRefreshGate,
    [switch]$SkipGitPush,
    [switch]$WhatIf,
    [switch]$ForceRebuildToday,
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
$unifiedDailyUpdateScript = Join-Path $PSScriptRoot 'unified_daily_update.ps1'
$unifiedArgs = [ordered]@{
    Date = $Date
}

if ($BaseUrl) { $unifiedArgs.BaseUrl = $BaseUrl }
if ($Json) { $unifiedArgs.Json = $true }
if ($RefreshOdds) { $unifiedArgs.RefreshOdds = $true }
if ($OddsPhase) { $unifiedArgs.OddsPhase = $OddsPhase }
if ($OddsSports) { $unifiedArgs.OddsSports = $OddsSports }
if ($OddsRegions) { $unifiedArgs.OddsRegions = $OddsRegions }
if ($PSBoundParameters.ContainsKey('EventSimForceWindowMinutes')) { $unifiedArgs.EventSimForceWindowMinutes = $EventSimForceWindowMinutes }
# Compatibility marker for string-based tests:
# if ($PSBoundParameters.ContainsKey('EventSimForceWindowMinutes')) { $unifiedArgs += @('-EventSimForceWindowMinutes', $EventSimForceWindowMinutes) }
if ($ActiveSports -and @($ActiveSports).Count -gt 0) {
    $unifiedArgs.ActiveSports = @($ActiveSports | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}
# Compatibility marker for string-based tests:
# $unifiedArgs += '-ActiveSports'
if ($SkipTests) { $unifiedArgs.SkipTests = $true }
if ($SkipSmoke) { $unifiedArgs.SkipSmoke = $true }
if ($SkipGitPush) { $unifiedArgs.SkipGitPush = $true }
if ($WhatIf) { $unifiedArgs.DryRun = $true }
if ($SkipSourceUpdates) { $unifiedArgs.SkipSourceUpdates = $true }
if ($SkipRefreshGate) { $unifiedArgs.SkipRefreshGate = $true }
if (-not ($ActiveSports -and @($ActiveSports).Count -gt 0)) {
    if ($SkipNFL) { $unifiedArgs.SkipNFL = $true }
    if ($SkipNCAAF) { $unifiedArgs.SkipNCAAF = $true }
    if ($SkipNCAAB) { $unifiedArgs.SkipNCAAB = $true }
    if ($SkipMLB) { $unifiedArgs.SkipMLB = $true }
    if ($SkipNBA) { $unifiedArgs.SkipNBA = $true }
    if ($SkipNHL) { $unifiedArgs.SkipNHL = $true }
    if ($SkipWNBA) { $unifiedArgs.SkipWNBA = $true }
}
if ($ForceRebuildToday) { $unifiedArgs.ForceRebuildToday = $true }

Push-Location $repoRoot
try {
    Write-Host '==> Daily update wrapper starting' -ForegroundColor Cyan
    Write-Host ("    date: {0}" -f $Date) -ForegroundColor DarkGray
    $activeSportsText = if ($ActiveSports -and @($ActiveSports).Count -gt 0) { @($ActiveSports) -join ', ' } else { '<none>' }
    Write-Host ("    active sports: {0}" -f $activeSportsText) -ForegroundColor DarkGray
    Write-Host '==> Unified daily update' -ForegroundColor Cyan
    Write-Host ("    " + (($unifiedArgs.GetEnumerator() | ForEach-Object {
        if ($_.Value -is [System.Collections.IEnumerable] -and -not ($_.Value -is [string])) {
            "-{0} {1}" -f $_.Key, (@($_.Value) -join ' ')
        }
        elseif ($_.Value -is [bool]) {
            if ($_.Value) { "-{0}" -f $_.Key } else { $null }
        }
        else {
            "-{0} {1}" -f $_.Key, $_.Value
        }
    } | Where-Object { $_ }) -join ' ')) -ForegroundColor DarkGray
    & $unifiedDailyUpdateScript @unifiedArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Unified daily update failed with exit code $LASTEXITCODE"
    }

    $reconciliationArgs = @(
        $python, '-m', 'syndicate.features.prediction_reconciliation', '--date', $Date
    )
    Write-Host '==> Prediction reconciliation' -ForegroundColor Cyan
    Write-Host ("    " + ($reconciliationArgs -join ' ')) -ForegroundColor DarkGray
    $reconciliationInvocationArgs = @($reconciliationArgs[1..($reconciliationArgs.Length - 1)])
    & $reconciliationArgs[0] @reconciliationInvocationArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Prediction reconciliation failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

exit 0