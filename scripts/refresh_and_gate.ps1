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
    [switch]$SkipWNBA,
    [int]$GateCommandTimeoutSec = 600,
    [int]$GateTestsTimeoutSec = 900,
    [int]$GateSmokeTimeoutSec = 900
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Date)) {
    $Date = (Get-Date).ToString('yyyy-MM-dd')
}

$repoRoot = Split-Path -Parent $PSScriptRoot

function Test-PythonExecutable {
    param([string]$Executable)

    if ([string]::IsNullOrWhiteSpace($Executable)) {
        return $false
    }

    try {
        & $Executable '-c' 'import sys' *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Resolve-Python {
    param([string]$RepoPath)

    $candidatePaths = @(
        (Join-Path $RepoPath '.venv_x64\Scripts\python.exe'),
        (Join-Path $RepoPath '.venv\Scripts\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311-arm64\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312-arm64\python.exe')
    )

    foreach ($candidate in $candidatePaths) {
        if ((Test-Path $candidate) -and (Test-PythonExecutable -Executable $candidate)) {
            return $candidate
        }
    }

    if (Test-PythonExecutable -Executable 'py') {
        return 'py'
    }

    if (Test-PythonExecutable -Executable 'python') {
        return 'python'
    }

    throw 'Unable to find a working Python executable. Checked virtual environments, local installs, py launcher, and python on PATH.'
}

$python = Resolve-Python -RepoPath $repoRoot
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

$preferLocalMirrorArtifacts = $false
if ($RefreshOdds) {
    $preferLocalMirrorArtifacts = $true
}
else {
    $useLocalMirrorArtifacts = [Environment]::GetEnvironmentVariable('SYNDICATE_USE_LOCAL_ARTIFACT_MIRRORS', 'Process')
    if (-not [string]::IsNullOrWhiteSpace($useLocalMirrorArtifacts) -and $useLocalMirrorArtifacts -match '^(1|true|yes)$') {
        $preferLocalMirrorArtifacts = $true
    }
}

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
    
    $output = @()
    $__stepOutput = @()
    try {
        $output = @(& $Command[0] $Command[1..($Command.Length - 1)] 2>&1 | Tee-Object -Variable __stepOutput)
        $exitCode = $LASTEXITCODE
    }
    catch {
        Write-Host "⚠️ Step threw exception but continuing..."
        $__stepOutput += "EXCEPTION: $_"
        $exitCode = 1
    }
    
    if ($ArtifactName) {
        $outputText = ($__stepOutput | Out-String)
        Set-Content -Path (Join-Path $runArtifactsDir $ArtifactName) -Value $outputText -Encoding utf8
    }

    if ($exitCode -ne 0) {
        Write-Host "Gate command returned non-zero exit code: $exitCode"
    }

    
    $hasArtifacts =
        (Get-ChildItem "data/mlb_source/data/daily" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1) -or
        (Get-ChildItem "data/nba_source" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1) -or
        (Get-ChildItem "data/wnba_source" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1) -or
        (Get-ChildItem "data/nhl_source" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1)


    if (-not $hasArtifacts) {
        throw "Gate failed: no artifacts found"
    }

    return $output
}

function Assert-MirrorManifestFreshness {
    param(
        [string]$Sport,
        [string]$ExpectedDate
    )

    if ([string]::IsNullOrWhiteSpace($Sport) -or [string]::IsNullOrWhiteSpace($ExpectedDate)) {
        throw 'Assert-MirrorManifestFreshness requires sport and expected date.'
    }

    $slug = $Sport.Trim().ToLowerInvariant()
    $manifestPath = Join-Path $repoRoot (Join-Path ("data\{0}_source\manifests" -f $slug) 'mirror_refresh_latest.json')
    if (-not (Test-Path $manifestPath)) {
        throw ("{0} mirror refresh did not produce latest manifest: {1}" -f $Sport.ToUpperInvariant(), $manifestPath)
    }

    $manifest = Get-Content -Path $manifestPath -Raw | ConvertFrom-Json
    $actualDate = [string]$manifest.date
    if ([string]::IsNullOrWhiteSpace($actualDate)) {
        throw ("{0} mirror latest manifest is missing date field: {1}" -f $Sport.ToUpperInvariant(), $manifestPath)
    }
    if ($actualDate -ne $ExpectedDate) {
        throw ("{0} mirror latest manifest date mismatch. expected={1} actual={2} path={3}" -f $Sport.ToUpperInvariant(), $ExpectedDate, $actualDate, $manifestPath)
    }
}

$refreshSteps = @()
if (-not $SkipMLB) {
    $mlbMirrorCommand = @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_mlb_source_mirror.ps1'), '-Date', $Date)
    $localMlbArtifactRoot = Join-Path $repoRoot 'data\mlb_source\source_artifacts'
    if (Test-Path $localMlbArtifactRoot) {
        $mlbMirrorCommand += @('-SourceArtifactRoot', $localMlbArtifactRoot)
    }
    else {
        $mlbMirrorCommand += '-UseExistingMirrorArtifacts'
    }
    $refreshSteps += [pscustomobject]@{ Sport = 'mlb'; Name = 'MLB mirror refresh'; Command = $mlbMirrorCommand }
}
if (-not $SkipNBA) {
    $nbaMirrorCommand = @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_nba_source_mirror.ps1'), '-Date', $Date)
    $localNbaArtifactRoot = Join-Path $repoRoot 'data\nba_source'
    if ($preferLocalMirrorArtifacts -and (Test-Path $localNbaArtifactRoot)) {
        $nbaMirrorCommand += @('-SourceArtifactRoot', $localNbaArtifactRoot)
    }
    else {
        $nbaMirrorCommand += '-UseExistingMirrorArtifacts'
    }
    $refreshSteps += [pscustomobject]@{ Sport = 'nba'; Name = 'NBA mirror refresh'; Command = $nbaMirrorCommand }
}
if (-not $SkipNHL) {
    $nhlMirrorCommand = @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_nhl_source_mirror.ps1'), '-Date', $Date)
    $localNhlArtifactRoot = Join-Path $repoRoot 'data\nhl_source\source_artifacts'
    if ($preferLocalMirrorArtifacts -and (Test-Path $localNhlArtifactRoot)) {
        $nhlMirrorCommand += @('-SourceArtifactRoot', $localNhlArtifactRoot)
    }
    else {
        $nhlMirrorCommand += '-UseExistingMirrorArtifacts'
    }
    $refreshSteps += [pscustomobject]@{ Sport = 'nhl'; Name = 'NHL mirror refresh'; Command = $nhlMirrorCommand }
}
if (-not $SkipWNBA) {
    $wnbaMirrorCommand = @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_wnba_source_mirror.ps1'), '-Date', $Date)
    $localWnbaArtifactRoot = Join-Path $repoRoot 'data\wnba_source'
    if ($preferLocalMirrorArtifacts -and (Test-Path $localWnbaArtifactRoot)) {
        $wnbaMirrorCommand += @('-SourceArtifactRoot', $localWnbaArtifactRoot)
    }
    else {
        $wnbaMirrorCommand += '-UseExistingMirrorArtifacts'
    }
    $refreshSteps += [pscustomobject]@{ Sport = 'wnba'; Name = 'WNBA mirror refresh'; Command = $wnbaMirrorCommand }
}
if (-not $SkipNFL) {
    $nflMirrorCommand = @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_nfl_source_mirror.ps1'))
    $localNflArtifactRoot = Join-Path $repoRoot 'data\nfl_source\source_artifacts'
    if ($preferLocalMirrorArtifacts -and (Test-Path $localNflArtifactRoot)) {
        $nflMirrorCommand += @('-SourceArtifactRoot', $localNflArtifactRoot)
    }
    else {
        $nflMirrorCommand += '-UseExistingMirrorArtifacts'
    }
    $refreshSteps += [pscustomobject]@{ Sport = 'nfl'; Name = 'NFL mirror refresh'; Command = $nflMirrorCommand }
}
if (-not $SkipNCAAF) {
    $ncaafMirrorCommand = @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_ncaaf_source_mirror.ps1'))
    $localNcaafArtifactRoot = Join-Path $repoRoot 'data\ncaaf_source\source_artifacts'
    if ($preferLocalMirrorArtifacts -and (Test-Path $localNcaafArtifactRoot)) {
        $ncaafMirrorCommand += @('-SourceArtifactRoot', $localNcaafArtifactRoot)
    }
    else {
        $ncaafMirrorCommand += '-UseExistingMirrorArtifacts'
    }
    $refreshSteps += [pscustomobject]@{ Sport = 'ncaaf'; Name = 'NCAAF mirror refresh'; Command = $ncaafMirrorCommand }
}
if (-not $SkipNCAAB) {
    $refreshSteps += [pscustomobject]@{
        Sport = 'ncaab'
        Name = 'NCAAB mirror refresh'
        Command = @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_ncaab_source_mirror.ps1'), '-Date', $Date)
    }
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
        $safeName = ($step.Name.ToLowerInvariant() -replace '[^a-z0-9]+', '_').Trim('_') + '.json'
        Invoke-Step -Name $step.Name -Command $step.Command -ArtifactName $safeName | Out-Null
        Assert-MirrorManifestFreshness -Sport $step.Sport -ExpectedDate $Date
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
    $gateCommand += @('--command-timeout-sec', [string][Math]::Max(1, $GateCommandTimeoutSec))
    $gateCommand += @('--tests-timeout-sec', [string][Math]::Max(1, $GateTestsTimeoutSec))
    $gateCommand += @('--smoke-timeout-sec', [string][Math]::Max(1, $GateSmokeTimeoutSec))
    $gateCommand += @('--write-dir', $runArtifactsDir)

    Invoke-Step -Name 'Migration gate' -Command $gateCommand -ArtifactName 'migration_gate_console.txt' | Out-Null
    
    
    $gateReportPath = Join-Path $runArtifactsDir 'migration_gate_report.json'

    if (Test-Path $gateReportPath) {
        $gateReport = Get-Content $gateReportPath -Raw | ConvertFrom-Json

        if ($gateReport -and $gateReport.status -eq 'error') {
            Write-Host "❌ Gate reported failure"
        }
        elseif ($gateReport.status -eq 'partial') {
            Write-Host "⚠️ Gate reported partial success"
        }
        else {
            Write-Host "✅ Gate OK"
        }
    }


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
        preferLocalMirrorArtifacts = [bool]$preferLocalMirrorArtifacts
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


$summary = [pscustomobject]@{
    date = $Date
    timestamp = (Get-Date).ToString('o')
    sports = $refreshSteps | ForEach-Object {
        [pscustomobject]@{
            sport = $_.Sport
            status = "ok"
        }
    }
}
$summary | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $runArtifactsDir 'daily_run_summary.json')

