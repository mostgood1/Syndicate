param(
    [string]$Date = (Get-Date).ToString('yyyy-MM-dd'),
    [string]$BaseUrl,
    [switch]$Json,
    [switch]$RefreshOdds,
    [string]$OddsPhase = 'all',
    [string]$OddsSports = 'all',
    [string]$OddsRegions = 'us',
    [switch]$SkipTests,
    [switch]$SkipSmoke,
    [switch]$SkipNFL,
    [switch]$SkipNCAAF,
    [switch]$SkipNCAAB,
    [switch]$SkipMLB,
    [switch]$SkipNBA,
    [switch]$SkipNHL,
    [switch]$SkipWNBA
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'py' }
$runStamp = (Get-Date).ToString('yyyyMMdd_HHmmss')
$runDir = Join-Path $repoRoot (Join-Path 'reports\daily_update' (Join-Path $Date $runStamp))
$latestDir = Join-Path $repoRoot 'reports\daily_update\latest'

New-Item -ItemType Directory -Path $runDir -Force | Out-Null
New-Item -ItemType Directory -Path $latestDir -Force | Out-Null

function Invoke-Step {
    param(
        [string]$Name,
        [string[]]$Command
    )

    Write-Host "==> $Name" -ForegroundColor Cyan
    Write-Host ("    " + ($Command -join ' ')) -ForegroundColor DarkGray
    & $Command[0] $Command[1..($Command.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

Push-Location $repoRoot
try {
    $refreshAndGate = @(
        'powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_and_gate.ps1'),
        '-Date', $Date,
        '-ArtifactsDir', (Join-Path $runDir 'migration')
    )
    if ($BaseUrl) { $refreshAndGate += @('-BaseUrl', $BaseUrl) }
    if ($Json) { $refreshAndGate += '-Json' }
    if ($RefreshOdds) { $refreshAndGate += '-RefreshOdds' }
    if ($OddsPhase) { $refreshAndGate += @('-OddsPhase', $OddsPhase) }
    if ($OddsSports) { $refreshAndGate += @('-OddsSports', $OddsSports) }
    if ($OddsRegions) { $refreshAndGate += @('-OddsRegions', $OddsRegions) }
    if ($SkipTests) { $refreshAndGate += '-SkipTests' }
    if ($SkipSmoke) { $refreshAndGate += '-SkipSmoke' }
    if ($SkipNFL) { $refreshAndGate += '-SkipNFL' }
    if ($SkipNCAAF) { $refreshAndGate += '-SkipNCAAF' }
    if ($SkipNCAAB) { $refreshAndGate += '-SkipNCAAB' }
    if ($SkipMLB) { $refreshAndGate += '-SkipMLB' }
    if ($SkipNBA) { $refreshAndGate += '-SkipNBA' }
    if ($SkipNHL) { $refreshAndGate += '-SkipNHL' }
    if ($SkipWNBA) { $refreshAndGate += '-SkipWNBA' }
    Invoke-Step -Name 'Refresh and gate' -Command $refreshAndGate

    $moduleTrackerPath = Join-Path $runDir 'module_tracker_snapshot.json'
    $moduleGapReportPath = Join-Path $runDir 'module_tracker_gap_report.txt'
    Invoke-Step -Name 'Module tracker snapshot' -Command @($python, '.\scripts\module_tracker_snapshot.py', '--write', $moduleTrackerPath, '--write-text', $moduleGapReportPath, '--json')

    $latestManifest = [pscustomobject]@{
        date = $Date
        generatedAt = (Get-Date).ToString('o')
        latestRunDir = $runDir
        migrationArtifactsDir = (Join-Path $runDir 'migration')
        moduleTracker = $moduleTrackerPath
        moduleGapReport = $moduleGapReportPath
        baseUrl = $BaseUrl
        refreshOdds = [bool]$RefreshOdds
        oddsPhase = $OddsPhase
        oddsSports = $OddsSports
        oddsRegions = $OddsRegions
    }
    $latestManifest | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $runDir 'daily_update_manifest.json') -Encoding utf8
    $latestManifest | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $latestDir 'daily_update_latest.json') -Encoding utf8
    Copy-Item -Path $moduleTrackerPath -Destination (Join-Path $latestDir 'module_tracker_snapshot.json') -Force
    Copy-Item -Path $moduleGapReportPath -Destination (Join-Path $latestDir 'module_tracker_gap_report.txt') -Force
    Copy-Item -Path (Join-Path $runDir 'daily_update_manifest.json') -Destination (Join-Path $latestDir 'daily_update_manifest.json') -Force
}
finally {
    Pop-Location
}