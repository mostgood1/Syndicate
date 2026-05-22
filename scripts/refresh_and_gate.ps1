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
    [string]$ArtifactsDir,
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
$runArtifactsDir = if ($ArtifactsDir) {
    if ([System.IO.Path]::IsPathRooted($ArtifactsDir)) { $ArtifactsDir } else { Join-Path $repoRoot $ArtifactsDir }
}
else {
    Join-Path $repoRoot (Join-Path 'reports\migration_runs' (Join-Path $Date $runStamp))
}
$refreshStatusRoot = Join-Path $repoRoot 'reports\refresh_status'
$refreshStatusRunDir = Join-Path $refreshStatusRoot (Join-Path $Date $runStamp)
$refreshStatusLatestDir = Join-Path $refreshStatusRoot 'latest'

New-Item -ItemType Directory -Path $runArtifactsDir -Force | Out-Null
New-Item -ItemType Directory -Path $refreshStatusRunDir -Force | Out-Null
New-Item -ItemType Directory -Path $refreshStatusLatestDir -Force | Out-Null

function Write-JsonArtifact {
    param(
        [string]$Name,
        [Parameter(ValueFromPipeline = $true)]
        $Value
    )

    $path = Join-Path $runArtifactsDir $Name
    $Value | ConvertTo-Json -Depth 10 | Set-Content -Path $path -Encoding utf8
}

function Invoke-Step {
    param(
        [string]$Name,
        [string[]]$Command,
        [string]$ArtifactName
    )

    Write-Host "==> $Name" -ForegroundColor Cyan
    Write-Host ("    " + ($Command -join ' ')) -ForegroundColor DarkGray
    $output = & $Command[0] $Command[1..($Command.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }

    if ($ArtifactName) {
        $outputText = ($output | Out-String)
        Set-Content -Path (Join-Path $runArtifactsDir $ArtifactName) -Value $outputText -Encoding utf8
    }

    return $output
}

$refreshSteps = @()
if (-not $SkipMLB) {
    $refreshSteps += ,@('MLB mirror refresh', @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_mlb_source_mirror.ps1'), '-Date', $Date))
}
if (-not $SkipNBA) {
    $refreshSteps += ,@('NBA mirror refresh', @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_nba_source_mirror.ps1'), '-Date', $Date))
}
if (-not $SkipNHL) {
    $refreshSteps += ,@('NHL mirror refresh', @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_nhl_source_mirror.ps1'), '-Date', $Date))
}
if (-not $SkipWNBA) {
    $refreshSteps += ,@('WNBA mirror refresh', @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_wnba_source_mirror.ps1'), '-Date', $Date))
}
if (-not $SkipNFL) {
    $refreshSteps += ,@('NFL mirror refresh', @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_nfl_source_mirror.ps1')))
}
if (-not $SkipNCAAF) {
    $refreshSteps += ,@('NCAAF mirror refresh', @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_ncaaf_source_mirror.ps1')))
}
if (-not $SkipNCAAB) {
    $refreshSteps += ,@('NCAAB mirror refresh', @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_ncaab_source_mirror.ps1'), '-Date', $Date, '-RefreshRawOutputsFromSource'))
}

Push-Location $repoRoot
try {
    if ($RefreshOdds) {
        $oddsCommand = @(
            $python,
            '.\scripts\refresh_odds_sources.py',
            '--date', $Date,
            '--phase', $OddsPhase,
            '--sports', $OddsSports,
            '--regions', $OddsRegions,
            '--skip-mirror',
            '--json'
        )
        Invoke-Step -Name 'Central odds refresh' -Command $oddsCommand -ArtifactName 'odds_refresh.json' | Out-Null
    }

    foreach ($step in $refreshSteps) {
        $safeName = ($step[0].ToLowerInvariant() -replace '[^a-z0-9]+', '_').Trim('_') + '.json'
        Invoke-Step -Name $step[0] -Command $step[1] -ArtifactName $safeName | Out-Null
    }

    $gateCommand = @($python, '.\scripts\migration_gate.py')
    if ($BaseUrl) {
        $gateCommand += @('--base-url', $BaseUrl)
    }
    if ($Json) {
        $gateCommand += '--json'
    }
    if ($SkipTests) {
        $gateCommand += '--skip-tests'
    }
    if ($SkipSmoke) {
        $gateCommand += '--skip-smoke'
    }
    $gateCommand += @('--write-dir', $runArtifactsDir)

    $gateOutput = Invoke-Step -Name 'Migration gate' -Command $gateCommand -ArtifactName 'migration_gate_console.txt'
    $runSummary = [pscustomobject]@{
        date = $Date
        runStamp = $runStamp
        baseUrl = $BaseUrl
        artifactsDir = $runArtifactsDir
        refreshStatusDir = $refreshStatusRunDir
        jsonMode = [bool]$Json
        refreshOdds = [bool]$RefreshOdds
        oddsPhase = $OddsPhase
        oddsSports = $OddsSports
        oddsRegions = $OddsRegions
        skipTests = [bool]$SkipTests
        skipSmoke = [bool]$SkipSmoke
        skipNFL = [bool]$SkipNFL
        skipNCAAF = [bool]$SkipNCAAF
        skipNCAAB = [bool]$SkipNCAAB
        skipMLB = [bool]$SkipMLB
        skipNBA = [bool]$SkipNBA
        skipNHL = [bool]$SkipNHL
        skipWNBA = [bool]$SkipWNBA
    }
    $runSummary | Write-JsonArtifact -Name 'refresh_and_gate_run.json'

    $refreshStatusManifest = [pscustomobject]@{
        date = $Date
        runStamp = $runStamp
        generatedAt = (Get-Date).ToString('o')
        artifactsDir = $runArtifactsDir
        refreshStatusDir = $refreshStatusRunDir
        latestManifestPath = (Join-Path $refreshStatusLatestDir 'refresh_status_latest.json')
        refreshOdds = [bool]$RefreshOdds
        oddsPhase = $OddsPhase
        oddsSports = $OddsSports
        oddsRegions = $OddsRegions
        baseUrl = $BaseUrl
        jsonMode = [bool]$Json
        skipTests = [bool]$SkipTests
        skipSmoke = [bool]$SkipSmoke
        runSummaryPath = (Join-Path $runArtifactsDir 'refresh_and_gate_run.json')
        oddsRefreshPath = (Join-Path $runArtifactsDir 'odds_refresh.json')
        migrationGateReportPath = (Join-Path $runArtifactsDir 'migration_gate_report.json')
        migrationGateConsolePath = (Join-Path $runArtifactsDir 'migration_gate_console.txt')
    }
    $refreshStatusManifest | ConvertTo-Json -Depth 10 | Set-Content -Path (Join-Path $runArtifactsDir 'refresh_status_manifest.json') -Encoding utf8
    $refreshStatusManifest | ConvertTo-Json -Depth 10 | Set-Content -Path (Join-Path $refreshStatusRunDir 'refresh_status_manifest.json') -Encoding utf8
    $refreshStatusManifest | ConvertTo-Json -Depth 10 | Set-Content -Path (Join-Path $refreshStatusLatestDir 'refresh_status_latest.json') -Encoding utf8
}
finally {
    Pop-Location
}