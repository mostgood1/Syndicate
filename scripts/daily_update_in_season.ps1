<#
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- In-season orchestration wrapper for refresh, gate, and publish flow.

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
    [switch]$SkipTests,
    [switch]$SkipSmoke,
    [switch]$SkipSourceUpdates,
    [switch]$SkipRefreshGate,
    [switch]$RunGateTests,
    [switch]$RunGateSmoke,
    [switch]$SkipGitPush,
    [switch]$DryRun,
    [switch]$IncludeOffSeasonSports,
    [switch]$ForceRebuildToday,
    [switch]$ForceMLB,
    [switch]$ForceNBA,
    [switch]$ForceNHL,
    [switch]$ForceWNBA,
    [switch]$ForceNFL,
    [switch]$ForceNCAAF,
    [switch]$ForceNCAAB
)

$ErrorActionPreference = 'Stop'

# Use Central Time for date calculations to match Syndicate's timezone
if ([string]::IsNullOrWhiteSpace($Date)) {
    $centralTZ = [TimeZoneInfo]::FindSystemTimeZoneById("Central Standard Time")
    $Date = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $centralTZ).ToString('yyyy-MM-dd')
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$dailyUpdateScript = Join-Path $PSScriptRoot 'daily_update.ps1'

function Get-ActiveSportMap {
    param([datetime]$TargetDate)

    $month = [int]$TargetDate.Month
    $day = [int]$TargetDate.Day

    $mlbActive = ($month -ge 3 -and $month -le 10)
    $nbaActive = ($month -ge 10 -or $month -le 6)
    $nhlActive = ($month -ge 10 -or $month -le 6)
    $wnbaActive = ($month -ge 5 -and $month -le 10)
    $nflActive = ($month -ge 8 -or $month -le 2)
    $ncaafActive = ($month -eq 8 -and $day -ge 15) -or ($month -ge 9 -and $month -le 12) -or ($month -eq 1)
    $ncaabActive = ($month -ge 11 -or $month -le 4)

    return [ordered]@{
        MLB = $mlbActive
        NBA = $nbaActive
        NHL = $nhlActive
        WNBA = $wnbaActive
        NFL = $nflActive
        NCAAF = $ncaafActive
        NCAAB = $ncaabActive
    }
}

function Set-SportActive {
    param(
        [hashtable]$ActiveSports,
        [string]$Sport,
        [bool]$ForceActive
    )

    if ($ForceActive) {
        $ActiveSports[$Sport] = $true
    }
}

function Get-ScheduledGamesCheck {
    param(
        [string]$Sport,
        [string]$DateValue
    )

    $result = [ordered]@{
        known = $false
        hasGames = $true
        count = $null
        source = $null
        note = $null
    }

    try {
        switch ($Sport.ToUpperInvariant()) {
            'MLB' {
                $url = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=$DateValue"
                $payload = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 20
                $totalGames = $null
                if ($payload -and $payload.dates -and $payload.dates.Count -gt 0) {
                    $totalGames = [int]($payload.dates[0].totalGames)
                }
                $result.known = $true
                $result.source = 'mlb_statsapi_schedule'
                $result.count = ($totalGames -as [int])
                $result.hasGames = ([int]($totalGames -as [int]) -gt 0)
            }
            'NBA' {
                $scoreboardDate = $DateValue.Replace('-', '')
                $url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=$scoreboardDate"
                $payload = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 20
                $eventCount = if ($payload -and $payload.events) { [int]$payload.events.Count } else { 0 }
                $result.known = $true
                $result.source = 'espn_nba_scoreboard'
                $result.count = $eventCount
                $result.hasGames = ($eventCount -gt 0)
            }
            'WNBA' {
                $scoreboardDate = $DateValue.Replace('-', '')
                $url = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates=$scoreboardDate"
                $payload = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 20
                $eventCount = if ($payload -and $payload.events) { [int]$payload.events.Count } else { 0 }
                $result.known = $true
                $result.source = 'espn_wnba_scoreboard'
                $result.count = $eventCount
                $result.hasGames = ($eventCount -gt 0)
            }
            'NHL' {
                $url = "https://api-web.nhle.com/v1/schedule/$DateValue"
                $payload = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 20
                $gameCount = 0
                foreach ($week in @($payload.gameWeek)) {
                    if (-not $week) { continue }
                    if ([string]$week.date -ne $DateValue) { continue }
                    $gameCount += @($week.games).Count
                }
                $result.known = $true
                $result.source = 'nhle_schedule'
                $result.count = $gameCount
                $result.hasGames = ($gameCount -gt 0)
            }
            default {
                $result.note = 'No scheduled-games checker configured for this sport.'
            }
        }
    }
    catch {
        $result.note = $_.Exception.Message
    }

    return [pscustomobject]$result
}

try {
    $targetDate = [datetime]::ParseExact($Date, 'yyyy-MM-dd', $null)
}
catch {
    throw "Date must be ISO format yyyy-MM-dd. Received: $Date"
}

$activeSports = Get-ActiveSportMap -TargetDate $targetDate

if ($IncludeOffSeasonSports) {
    foreach ($sport in @($activeSports.Keys)) {
        $activeSports[$sport] = $true
    }
}

Set-SportActive -ActiveSports $activeSports -Sport 'MLB' -ForceActive ([bool]$ForceMLB)
Set-SportActive -ActiveSports $activeSports -Sport 'NBA' -ForceActive ([bool]$ForceNBA)
Set-SportActive -ActiveSports $activeSports -Sport 'NHL' -ForceActive ([bool]$ForceNHL)
Set-SportActive -ActiveSports $activeSports -Sport 'WNBA' -ForceActive ([bool]$ForceWNBA)
Set-SportActive -ActiveSports $activeSports -Sport 'NFL' -ForceActive ([bool]$ForceNFL)
Set-SportActive -ActiveSports $activeSports -Sport 'NCAAF' -ForceActive ([bool]$ForceNCAAF)
Set-SportActive -ActiveSports $activeSports -Sport 'NCAAB' -ForceActive ([bool]$ForceNCAAB)

if ($SkipTests -and $RunGateTests) {
    throw 'Pass either -SkipTests or -RunGateTests, not both.'
}

if ($SkipSmoke -and $RunGateSmoke) {
    throw 'Pass either -SkipSmoke or -RunGateSmoke, not both.'
}

$forcedMap = [ordered]@{
    MLB = [bool]$ForceMLB
    NBA = [bool]$ForceNBA
    NHL = [bool]$ForceNHL
    WNBA = [bool]$ForceWNBA
    NFL = [bool]$ForceNFL
    NCAAF = [bool]$ForceNCAAF
    NCAAB = [bool]$ForceNCAAB
}

$precheckActiveList = @($activeSports.GetEnumerator() | Where-Object { $_.Value } | ForEach-Object { $_.Key })
if ($precheckActiveList.Count -eq 0) {
    throw 'No sports are active for the selected date. Pass -IncludeOffSeasonSports or one or more -Force* switches.'
}

$noSlateSkips = @()
$scheduledChecks = @()
foreach ($sport in @('MLB', 'NBA', 'NHL', 'WNBA')) {
    if (-not $activeSports[$sport]) { continue }
    if ($IncludeOffSeasonSports) {
        $scheduledChecks += [pscustomobject]@{
            sport = $sport
            skipped = $false
            reason = 'IncludeOffSeasonSports enabled; bypassing no-slate schedule skip'
            checker = $null
            count = $null
        }
        continue
    }
    if ($forcedMap[$sport]) {
        $scheduledChecks += [pscustomobject]@{
            sport = $sport
            skipped = $false
            reason = 'Forced active via -Force* switch'
            checker = $null
            count = $null
        }
        continue
    }

    $check = Get-ScheduledGamesCheck -Sport $sport -DateValue $Date
    $scheduledChecks += [pscustomobject]@{
        sport = $sport
        skipped = [bool]($check.known -and -not $check.hasGames)
        reason = if ($check.known -and -not $check.hasGames) { 'No scheduled games detected for date' } elseif (-not $check.known) { "Checker unavailable: $($check.note)" } else { 'Scheduled games detected' }
        checker = $check.source
        count = $check.count
    }
    if ($sport -eq 'WNBA' -and $check.known -and -not $check.hasGames) {
        $scheduledChecks[-1].skipped = $false
        $scheduledChecks[-1].reason = 'WNBA schedule probe returned no games; keeping sport active to avoid false-negative skips'
    }
    if ($check.known -and -not $check.hasGames -and $sport -ne 'WNBA') {
        $activeSports[$sport] = $false
        $noSlateSkips += $sport
    }
}

$activeList = @($activeSports.GetEnumerator() | Where-Object { $_.Value } | ForEach-Object { $_.Key })
if ($activeSports['WNBA'] -and -not ($activeList -contains 'WNBA')) {
    $activeList += 'WNBA'
}
$skippedList = @($activeSports.GetEnumerator() | Where-Object { -not $_.Value } | ForEach-Object { $_.Key })

if ($activeList.Count -eq 0) {
    Write-Host '==> In-season daily update' -ForegroundColor Cyan
    Write-Host ("    date: {0}" -f $Date) -ForegroundColor DarkGray
    Write-Host '    no-slate day detected for scheduled-game sports; skipping run.' -ForegroundColor Yellow
    if ($noSlateSkips.Count -gt 0) {
        Write-Host ("    no-slate skips: {0}" -f ($noSlateSkips -join ', ')) -ForegroundColor DarkGray
    }
    return
}

$dailyArgs = @(
    'powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', $dailyUpdateScript,
    '-Date', $Date
)

$effectiveSkipTests = [bool]$SkipTests
$effectiveSkipSmoke = [bool]$SkipSmoke

if ($BaseUrl) { $dailyArgs += @('-BaseUrl', $BaseUrl) }
if ($Json) { $dailyArgs += '-Json' }
if ($RefreshOdds) { $dailyArgs += '-RefreshOdds' }
if ($OddsPhase) { $dailyArgs += @('-OddsPhase', $OddsPhase) }
if ($OddsSports) { $dailyArgs += @('-OddsSports', $OddsSports) }
if ($OddsRegions) { $dailyArgs += @('-OddsRegions', $OddsRegions) }
if ($PSBoundParameters.ContainsKey('EventSimForceWindowMinutes')) { $dailyArgs += @('-EventSimForceWindowMinutes', $EventSimForceWindowMinutes) }
if ($effectiveSkipTests) { $dailyArgs += '-SkipTests' }
if ($effectiveSkipSmoke) { $dailyArgs += '-SkipSmoke' }
if ($SkipSourceUpdates) { $dailyArgs += '-SkipSourceUpdates' }
if ($SkipRefreshGate) { $dailyArgs += '-SkipRefreshGate' }
if ($SkipGitPush) { $dailyArgs += '-SkipGitPush' }
if ($DryRun) { $dailyArgs += '-WhatIf' }
if ($ForceRebuildToday) { $dailyArgs += '-ForceRebuildToday' }
if ($activeList.Count -gt 0) {
    $dailyArgs += '-ActiveSports'
    $dailyArgs += @($activeList)
}

Write-Host '==> In-season daily update' -ForegroundColor Cyan
Write-Host ("    date: {0}" -f $Date) -ForegroundColor DarkGray
Write-Host ("    active sports: {0}" -f ($activeList -join ', ')) -ForegroundColor DarkGray
if ($skippedList.Count -gt 0) {
    Write-Host ("    skipped sports: {0}" -f ($skippedList -join ', ')) -ForegroundColor DarkGray
}
if ($noSlateSkips.Count -gt 0) {
    Write-Host ("    no-slate skips: {0}" -f ($noSlateSkips -join ', ')) -ForegroundColor DarkGray
}
foreach ($check in $scheduledChecks) {
    $countText = if ($null -eq $check.count) { '-' } else { [string]$check.count }
    $checkerText = if ([string]::IsNullOrWhiteSpace([string]$check.checker)) { 'n/a' } else { [string]$check.checker }
    Write-Host ("    schedule check [{0}] count={1} source={2} status={3}" -f $check.sport, $countText, $checkerText, $check.reason) -ForegroundColor DarkGray
}
$gateTestsStatus = 'enabled'
if ($effectiveSkipTests) {
    $gateTestsStatus = 'skipped'
}
$gateSmokeStatus = 'enabled'
if ($effectiveSkipSmoke) {
    $gateSmokeStatus = 'skipped'
}
Write-Host ("    gate tests: {0}" -f $gateTestsStatus) -ForegroundColor DarkGray
Write-Host ("    gate smoke: {0}" -f $gateSmokeStatus) -ForegroundColor DarkGray
if ($RefreshOdds) {
    Write-Host ("    central odds refresh: enabled phase={0} sports={1} regions={2}" -f $OddsPhase, $OddsSports, $OddsRegions) -ForegroundColor DarkGray
}
Write-Host ("    " + ($dailyArgs -join ' ')) -ForegroundColor DarkGray

if ($DryRun) {
    return
}

function Sync-SportSourceArtifacts {
    param(
        [string]$Sport,
        [string]$RepoRootPath
    )

    if ([string]::IsNullOrWhiteSpace($Sport) -or [string]::IsNullOrWhiteSpace($RepoRootPath)) {
        return
    }

    $sportSlug = $Sport.Trim().ToLowerInvariant()
    $sourceDataRoot = Join-Path $RepoRootPath ("data\{0}_source\data" -f $sportSlug)
    $artifactDataRoot = Join-Path $RepoRootPath ("data\{0}_source\source_artifacts\data" -f $sportSlug)

    if (-not (Test-Path $sourceDataRoot)) {
        return
    }

    New-Item -ItemType Directory -Path $artifactDataRoot -Force | Out-Null

    $robocopyArgs = @(
        $sourceDataRoot
        $artifactDataRoot
        '/E'
        '/FFT'
        '/R:1'
        '/W:1'
        '/NFL'
        '/NDL'
        '/NJH'
        '/NJS'
        '/NP'
        '/XD'
        'cache'
    )

    & robocopy @robocopyArgs | Out-Null
    $exitCode = $LASTEXITCODE
    if ($exitCode -ge 8) {
        throw "Robocopy failed for $sportSlug with exit code $exitCode"
    }

    Write-Host ("    synced source_artifacts for {0}: robocopy exit {1}" -f $sportSlug, $exitCode) -ForegroundColor DarkGray
}

Push-Location $repoRoot
try {
    & $dailyArgs[0] $dailyArgs[1..($dailyArgs.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "In-season daily update failed with exit code $LASTEXITCODE"
    }

    foreach ($sport in @('mlb', 'nba', 'wnba', 'nhl', 'nfl', 'ncaaf', 'ncaab')) {
        if ($activeSports[$sport.ToUpperInvariant()]) {
            Sync-SportSourceArtifacts -Sport $sport -RepoRootPath $repoRoot
        }
    }
}
finally {
    Pop-Location
}

exit 0