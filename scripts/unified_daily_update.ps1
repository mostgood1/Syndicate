param(
    [string]$Date = (Get-Date).ToString('yyyy-MM-dd'),
    [string]$BaseUrl,
    [switch]$Json,
    [switch]$SkipTests,
    [switch]$SkipSmoke,
    [switch]$SkipSourceUpdates,
    [switch]$SkipRefreshGate,
    [switch]$DryRun,
    [switch]$SkipMLB,
    [switch]$SkipNBA,
    [switch]$SkipNHL,
    [switch]$SkipWNBA,
    [switch]$SkipNFL,
    [switch]$SkipNCAAF,
    [switch]$SkipNCAAB
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$season = ($Date -split '-')[0]
$runStamp = (Get-Date).ToString('yyyyMMdd_HHmmss')
$runDir = Join-Path $repoRoot (Join-Path 'reports\daily_update' (Join-Path $Date $runStamp))
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

function Invoke-Step {
    param(
        [string]$Name,
        [string[]]$Command,
        [string]$WorkingDirectory
    )

    Write-Host "==> $Name" -ForegroundColor Cyan
    if ($WorkingDirectory) {
        Write-Host "    cwd: $WorkingDirectory" -ForegroundColor DarkGray
    }
    Write-Host ("    " + ($Command -join ' ')) -ForegroundColor DarkGray

    if ($DryRun) {
        return
    }

    Push-Location $WorkingDirectory
    try {
        & $Command[0] $Command[1..($Command.Length - 1)]
        if ($LASTEXITCODE -ne 0) {
            throw "$Name failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

function Resolve-Python {
    param([string]$RepoPath)

    $venvPython = Join-Path $RepoPath '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) {
        return $venvPython
    }
    return 'python'
}

$sourceSteps = @()

if (-not $SkipMLB) {
    $mlbRoot = Join-Path $repoRoot '..\MLB-BettingV2'
    $sourceSteps += ,@('MLB source daily update', @((Resolve-Python $mlbRoot), 'tools\daily_update.py', '--date', $Date, '--season', $season, '--workflow', 'ui-daily', '--git-push', 'off'), $mlbRoot)
}
if (-not $SkipNBA) {
    $nbaRoot = Join-Path $repoRoot '..\NBA-Betting'
    $sourceSteps += ,@('NBA source daily update', @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', '.\scripts\daily_update.ps1', '-Date', $Date), $nbaRoot)
}
if (-not $SkipWNBA) {
    $wnbaRoot = Join-Path $repoRoot '..\WNBA-Betting'
    $sourceSteps += ,@('WNBA source daily update', @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', '.\scripts\daily_update.ps1', '-Date', $Date), $wnbaRoot)
}
if (-not $SkipNHL) {
    $nhlRoot = Join-Path $repoRoot '..\NHL-Betting'
    $sourceSteps += ,@('NHL source daily update', @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', '.\scripts\daily_update.ps1', '-BaseDate', $Date, '-NoGitPush'), $nhlRoot)
}
if (-not $SkipNFL) {
    $nflRoot = Join-Path $repoRoot '..\NFL-Betting'
    $sourceSteps += ,@('NFL source daily update', @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', '.\daily_update.ps1', '-GitPush:$false'), $nflRoot)
}
if (-not $SkipNCAAF) {
    $ncaafRoot = Join-Path $repoRoot '..\NCAAFCompare'
    $sourceSteps += ,@('NCAAF source daily update', @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', '.\Run-DailyUpdate.ps1', '-DisableGitPush'), $ncaafRoot)
}
if (-not $SkipNCAAB) {
    $ncaabRoot = Join-Path $repoRoot '..\NCAAB'
    $sourceSteps += ,@('NCAAB source daily update', @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', '.\scripts\daily_update.ps1', '-Today', $Date, '-SkipGitPush'), $ncaabRoot)
}

Push-Location $repoRoot
try {
    if (-not $SkipSourceUpdates) {
        foreach ($step in $sourceSteps) {
            Invoke-Step -Name $step[0] -Command $step[1] -WorkingDirectory $step[2]
        }
    }

    if (-not $SkipRefreshGate) {
        $refreshArgs = @(
            'powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_and_gate.ps1'),
            '-Date', $Date,
            '-ArtifactsDir', (Join-Path $runDir 'migration')
        )
        if ($BaseUrl) { $refreshArgs += @('-BaseUrl', $BaseUrl) }
        if ($Json) { $refreshArgs += '-Json' }
        if ($SkipTests) { $refreshArgs += '-SkipTests' }
        if ($SkipSmoke) { $refreshArgs += '-SkipSmoke' }
        if ($SkipMLB) { $refreshArgs += '-SkipMLB' }
        if ($SkipNBA) { $refreshArgs += '-SkipNBA' }
        if ($SkipNHL) { $refreshArgs += '-SkipNHL' }
        if ($SkipWNBA) { $refreshArgs += '-SkipWNBA' }
        if ($SkipNFL) { $refreshArgs += '-SkipNFL' }
        if ($SkipNCAAF) { $refreshArgs += '-SkipNCAAF' }
        if ($SkipNCAAB) { $refreshArgs += '-SkipNCAAB' }
        Invoke-Step -Name 'Syndicate refresh and gate' -Command $refreshArgs -WorkingDirectory $repoRoot
    }

    [pscustomobject]@{
        date = $Date
        runDir = $runDir
        skipped = [ordered]@{
            sourceUpdates = [bool]$SkipSourceUpdates
            refreshGate = [bool]$SkipRefreshGate
            mlb = [bool]$SkipMLB
            nba = [bool]$SkipNBA
            nhl = [bool]$SkipNHL
            wnba = [bool]$SkipWNBA
            nfl = [bool]$SkipNFL
            ncaaf = [bool]$SkipNCAAF
            ncaab = [bool]$SkipNCAAB
        }
        dryRun = [bool]$DryRun
    } | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $runDir 'unified_daily_update_run.json') -Encoding utf8
}
finally {
    Pop-Location
}