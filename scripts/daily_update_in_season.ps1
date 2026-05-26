param(
    [string]$Date = (Get-Date).ToString('yyyy-MM-dd'),
    [string]$BaseUrl,
    [switch]$Json,
    [switch]$SkipTests,
    [switch]$SkipSmoke,
    [switch]$SkipSourceUpdates,
    [switch]$SkipRefreshGate,
    [switch]$RunGateTests,
    [switch]$RunGateSmoke,
    [switch]$SkipGitPush,
    [switch]$DryRun,
    [switch]$IncludeOffSeasonSports,
    [switch]$ForceMLB,
    [switch]$ForceNBA,
    [switch]$ForceNHL,
    [switch]$ForceWNBA,
    [switch]$ForceNFL,
    [switch]$ForceNCAAF,
    [switch]$ForceNCAAB
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Date)) {
    $Date = (Get-Date).ToString('yyyy-MM-dd')
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

$activeList = @($activeSports.GetEnumerator() | Where-Object { $_.Value } | ForEach-Object { $_.Key })
$skippedList = @($activeSports.GetEnumerator() | Where-Object { -not $_.Value } | ForEach-Object { $_.Key })

if ($activeList.Count -eq 0) {
    throw 'No sports are active for the selected date. Pass -IncludeOffSeasonSports or one or more -Force* switches.'
}

$dailyArgs = @(
    'powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', $dailyUpdateScript,
    '-Date', $Date
)

$effectiveSkipTests = [bool]$SkipTests -or (-not [bool]$RunGateTests)
$effectiveSkipSmoke = [bool]$SkipSmoke -or (-not [bool]$RunGateSmoke)

if ($BaseUrl) { $dailyArgs += @('-BaseUrl', $BaseUrl) }
if ($Json) { $dailyArgs += '-Json' }
if ($effectiveSkipTests) { $dailyArgs += '-SkipTests' }
if ($effectiveSkipSmoke) { $dailyArgs += '-SkipSmoke' }
if ($SkipSourceUpdates) { $dailyArgs += '-SkipSourceUpdates' }
if ($SkipRefreshGate) { $dailyArgs += '-SkipRefreshGate' }
if ($SkipGitPush) { $dailyArgs += '-SkipGitPush' }
if ($DryRun) { $dailyArgs += '-WhatIf' }

if (-not $activeSports.MLB) { $dailyArgs += '-SkipMLB' }
if (-not $activeSports.NBA) { $dailyArgs += '-SkipNBA' }
if (-not $activeSports.NHL) { $dailyArgs += '-SkipNHL' }
if (-not $activeSports.WNBA) { $dailyArgs += '-SkipWNBA' }
if (-not $activeSports.NFL) { $dailyArgs += '-SkipNFL' }
if (-not $activeSports.NCAAF) { $dailyArgs += '-SkipNCAAF' }
if (-not $activeSports.NCAAB) { $dailyArgs += '-SkipNCAAB' }

Write-Host '==> In-season daily update' -ForegroundColor Cyan
Write-Host ("    date: {0}" -f $Date) -ForegroundColor DarkGray
Write-Host ("    active sports: {0}" -f ($activeList -join ', ')) -ForegroundColor DarkGray
if ($skippedList.Count -gt 0) {
    Write-Host ("    skipped sports: {0}" -f ($skippedList -join ', ')) -ForegroundColor DarkGray
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
Write-Host ("    " + ($dailyArgs -join ' ')) -ForegroundColor DarkGray

if ($DryRun) {
    return
}

Push-Location $repoRoot
try {
    & $dailyArgs[0] $dailyArgs[1..($dailyArgs.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "In-season daily update failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}