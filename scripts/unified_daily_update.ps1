param(
    [string]$Date = (Get-Date).ToString('yyyy-MM-dd'),
    [string]$BaseUrl,
    [switch]$Json,
    [switch]$SkipTests,
    [switch]$SkipSmoke,
    [switch]$SkipSourceUpdates,
    [switch]$SkipRefreshGate,
    [switch]$SkipGitPush,
    [switch]$DryRun,
    [string]$GitRemote = 'origin',
    [string]$CommitMessagePrefix = 'daily update',
    [switch]$SkipMLB,
    [switch]$SkipNBA,
    [switch]$SkipNHL,
    [switch]$SkipWNBA,
    [switch]$SkipNFL,
    [switch]$SkipNCAAF,
    [switch]$SkipNCAAB
)

$ErrorActionPreference = 'Stop'

$cpuCount = [Environment]::ProcessorCount

function Get-ReasonableWorkerCount {
    param(
        [int]$Requested,
        [int]$CpuCount = $cpuCount
    )

    $safeCpu = [Math]::Max(1, [int]$CpuCount)
    $safeRequested = [Math]::Max(1, [int]$Requested)
    return [Math]::Min($safeRequested, [Math]::Max(1, $safeCpu - 1))
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$season = ($Date -split '-')[0]
$runStamp = (Get-Date).ToString('yyyyMMdd_HHmmss')
$runDir = Join-Path $repoRoot (Join-Path 'reports\daily_update' (Join-Path $Date $runStamp))
$latestDir = Join-Path $repoRoot 'reports\daily_update\latest'
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
New-Item -ItemType Directory -Path $latestDir -Force | Out-Null

$runtimePolicy = [ordered]@{
    NBA = [ordered]@{
        smartsimNSims = 1000
        smartsimWorkers = 4
    }
    WNBA = [ordered]@{
        smartsimNSims = 1000
        smartsimWorkers = 4
    }
    NHL = [ordered]@{
        gameSimSamples = 1000
        propsBoxscoreNSims = 1000
    }
    NFL = [ordered]@{
        scenarioNSims = 1000
    }
}

$runtimePolicy.NBA.smartsimWorkers = Get-ReasonableWorkerCount -Requested $runtimePolicy.NBA.smartsimWorkers
$runtimePolicy.WNBA.smartsimWorkers = Get-ReasonableWorkerCount -Requested $runtimePolicy.WNBA.smartsimWorkers

function Invoke-Step {
    param(
        [string]$Name,
        [string[]]$Command,
        [string]$WorkingDirectory,
        [hashtable]$EnvironmentOverrides
    )

    Write-Host "==> $Name" -ForegroundColor Cyan
    if ($WorkingDirectory) {
        Write-Host "    cwd: $WorkingDirectory" -ForegroundColor DarkGray
    }
    Write-Host ("    " + ($Command -join ' ')) -ForegroundColor DarkGray
    if ($EnvironmentOverrides -and $EnvironmentOverrides.Count -gt 0) {
        $envSummary = @($EnvironmentOverrides.GetEnumerator() | Sort-Object Name | ForEach-Object { "{0}={1}" -f $_.Key, $_.Value }) -join '; '
        Write-Host "    env: $envSummary" -ForegroundColor DarkGray
    }

    if ($DryRun) {
        return
    }

    Push-Location $WorkingDirectory
    $previousEnv = @{}
    try {
        if ($EnvironmentOverrides) {
            foreach ($entry in $EnvironmentOverrides.GetEnumerator()) {
                $previousEnv[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, 'Process')
                [Environment]::SetEnvironmentVariable($entry.Key, [string]$entry.Value, 'Process')
            }
        }
        & $Command[0] $Command[1..($Command.Length - 1)]
        if ($LASTEXITCODE -ne 0) {
            throw "$Name failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        if ($EnvironmentOverrides) {
            foreach ($entry in $EnvironmentOverrides.GetEnumerator()) {
                $priorValue = $previousEnv[$entry.Key]
                [Environment]::SetEnvironmentVariable($entry.Key, $priorValue, 'Process')
            }
        }
        Pop-Location
    }
}

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
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
    )
    foreach ($candidate in $candidatePaths) {
        if ((Test-Path $candidate) -and (Test-PythonExecutable -Executable $candidate)) {
            return $candidate
        }
    }
    if (Test-PythonExecutable -Executable 'python') {
        return 'python'
    }
    return 'python'
}

function Get-CurrentBranch {
    param([string]$RepoPath)

    Push-Location $RepoPath
    try {
        $branch = (& git branch --show-current | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) {
            throw "git branch --show-current failed for $RepoPath with exit code $LASTEXITCODE"
        }
        if (-not $branch) {
            throw "Unable to resolve current git branch for $RepoPath"
        }
        return $branch
    }
    finally {
        Pop-Location
    }
}

function Invoke-GitPublish {
    param(
        [string]$Name,
        [string]$RepoPath,
        [string]$CommitMessage,
        [string]$RemoteName
    )

    $result = [ordered]@{
        name = $Name
        repoPath = $RepoPath
        remote = $RemoteName
        branch = $null
        commitMessage = $CommitMessage
        status = 'skipped'
        commit = $null
    }

    if (-not (Test-Path (Join-Path $RepoPath '.git'))) {
        $result.status = 'not_a_git_repo'
        return [pscustomobject]$result
    }

    if ($DryRun) {
        $result.branch = Get-CurrentBranch -RepoPath $RepoPath
        $result.status = 'dry_run'
        return [pscustomobject]$result
    }

    Push-Location $RepoPath
    try {
        $result.branch = Get-CurrentBranch -RepoPath $RepoPath
        & git add -A
        if ($LASTEXITCODE -ne 0) {
            throw "git add failed for $RepoPath with exit code $LASTEXITCODE"
        }

        $statusLines = @(& git status --short)
        if ($LASTEXITCODE -ne 0) {
            throw "git status failed for $RepoPath with exit code $LASTEXITCODE"
        }
        if (-not $statusLines -or $statusLines.Count -eq 0) {
            $result.status = 'no_changes'
            return [pscustomobject]$result
        }

        & git commit -m $CommitMessage
        if ($LASTEXITCODE -ne 0) {
            throw "git commit failed for $RepoPath with exit code $LASTEXITCODE"
        }

        $result.commit = (& git rev-parse HEAD | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) {
            throw "git rev-parse failed for $RepoPath with exit code $LASTEXITCODE"
        }

        & git push $RemoteName $result.branch
        if ($LASTEXITCODE -ne 0) {
            throw "git push failed for $RepoPath with exit code $LASTEXITCODE"
        }

        $result.status = 'pushed'
        return [pscustomobject]$result
    }
    finally {
        Pop-Location
    }
}

$sourceSteps = @()
$publishRepos = @()

if (-not $SkipMLB) {
    $sourceSteps += [pscustomobject]@{
        Name = 'MLB Syndicate daily refresh'
        Command = @(
            (Resolve-Python $repoRoot),
            'scripts\refresh_mlb_oddsapi.py',
            '--date', $Date,
            '--source-root', 'data\mlb_source',
            '--artifact-root', 'data\mlb_source\source_artifacts',
            '--overwrite', 'on'
        )
        WorkingDirectory = $repoRoot
        EnvironmentOverrides = @{}
    }
}
if (-not $SkipNBA) {
    $nbaRoot = Join-Path $repoRoot '..\NBA-Betting'
    $sourceSteps += [pscustomobject]@{
        Name = 'NBA source daily update'
        Command = @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', '.\scripts\daily_update.ps1', '-Date', $Date, '-GitPush:$false')
        WorkingDirectory = $nbaRoot
        EnvironmentOverrides = @{
            DAILY_SMARTSIM_NSIMS = [string]$runtimePolicy.NBA.smartsimNSims
            DAILY_SMARTSIM_WORKERS = [string]$runtimePolicy.NBA.smartsimWorkers
        }
    }
    $publishRepos += [pscustomobject]@{ Name = 'NBA-Betting'; RepoPath = $nbaRoot; CommitMessage = "$CommitMessagePrefix $Date (NBA source daily update)" }
}
if (-not $SkipWNBA) {
    $wnbaRoot = Join-Path $repoRoot '..\WNBA-Betting'
    $sourceSteps += [pscustomobject]@{
        Name = 'WNBA source daily update'
        Command = @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', '.\scripts\daily_update.ps1', '-Date', $Date, '-GitPush:$false')
        WorkingDirectory = $wnbaRoot
        EnvironmentOverrides = @{
            DAILY_SMARTSIM_NSIMS = [string]$runtimePolicy.WNBA.smartsimNSims
            DAILY_SMARTSIM_WORKERS = [string]$runtimePolicy.WNBA.smartsimWorkers
        }
    }
    $publishRepos += [pscustomobject]@{ Name = 'WNBA-Betting'; RepoPath = $wnbaRoot; CommitMessage = "$CommitMessagePrefix $Date (WNBA source daily update)" }
}
if (-not $SkipNHL) {
    $nhlRoot = Join-Path $repoRoot '..\NHL-Betting'
    $sourceSteps += [pscustomobject]@{
        Name = 'NHL source daily update'
        Command = @(
            'powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', '.\scripts\daily_update.ps1',
            '-BaseDate', $Date,
            '-SimSamples', ([string]$runtimePolicy.NHL.gameSimSamples),
            '-PropsBoxscoreNSims', ([string]$runtimePolicy.NHL.propsBoxscoreNSims),
            '-NoGitPush'
        )
        WorkingDirectory = $nhlRoot
        EnvironmentOverrides = @{}
    }
    $publishRepos += [pscustomobject]@{ Name = 'NHL-Betting'; RepoPath = $nhlRoot; CommitMessage = "$CommitMessagePrefix $Date (NHL source daily update)" }
}
if (-not $SkipNFL) {
    $nflRoot = Join-Path $repoRoot '..\NFL-Betting'
    $sourceSteps += [pscustomobject]@{
        Name = 'NFL source daily update'
        Command = @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', '.\daily_update.ps1', '-GitPush:$false')
        WorkingDirectory = $nflRoot
        EnvironmentOverrides = @{
            DAILY_UPDATE_SCENARIO_N_SIMS = [string]$runtimePolicy.NFL.scenarioNSims
        }
    }
    $publishRepos += [pscustomobject]@{ Name = 'NFL-Betting'; RepoPath = $nflRoot; CommitMessage = "$CommitMessagePrefix $Date (NFL source daily update)" }
}
if (-not $SkipNCAAF) {
    $ncaafRoot = Join-Path $repoRoot '..\NCAAFCompare'
    $sourceSteps += [pscustomobject]@{
        Name = 'NCAAF source daily update'
        Command = @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', '.\Run-DailyUpdate.ps1', '-DisableGitPush')
        WorkingDirectory = $ncaafRoot
        EnvironmentOverrides = @{}
    }
    $publishRepos += [pscustomobject]@{ Name = 'NCAAFCompare'; RepoPath = $ncaafRoot; CommitMessage = "$CommitMessagePrefix $Date (NCAAF source daily update)" }
}
if (-not $SkipNCAAB) {
    $ncaabRoot = Join-Path $repoRoot '..\NCAAB'
    $sourceSteps += [pscustomobject]@{
        Name = 'NCAAB source daily update'
        Command = @('powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', '.\scripts\daily_update.ps1', '-Today', $Date, '-SkipGitPush')
        WorkingDirectory = $ncaabRoot
        EnvironmentOverrides = @{}
    }
    $publishRepos += [pscustomobject]@{ Name = 'NCAAB'; RepoPath = $ncaabRoot; CommitMessage = "$CommitMessagePrefix $Date (NCAAB source daily update)" }
}

$publishRepos += [pscustomobject]@{ Name = 'Syndicate'; RepoPath = $repoRoot; CommitMessage = "$CommitMessagePrefix $Date (Syndicate mirror + gate)" }

$runManifest = [ordered]@{
    date = $Date
    generatedAt = (Get-Date).ToString('o')
    runDir = $runDir
    latestDir = $latestDir
    runtimePolicy = $runtimePolicy
    sourceSteps = @($sourceSteps | ForEach-Object { [ordered]@{ name = $_.Name; workingDirectory = $_.WorkingDirectory; environmentOverrides = $_.EnvironmentOverrides; command = $_.Command } })
    skipGitPush = [bool]$SkipGitPush
    gitRemote = $GitRemote
    commitMessagePrefix = $CommitMessagePrefix
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
    pushResults = @()
}

Push-Location $repoRoot
try {
    if ($SkipRefreshGate -and -not $SkipGitPush) {
        throw 'Cannot push git updates when -SkipRefreshGate is set. Run the gate or pass -SkipGitPush.'
    }

    if (-not $SkipSourceUpdates) {
        foreach ($step in $sourceSteps) {
            Invoke-Step -Name $step.Name -Command $step.Command -WorkingDirectory $step.WorkingDirectory -EnvironmentOverrides $step.EnvironmentOverrides
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

    if (-not $SkipGitPush) {
        foreach ($repo in $publishRepos) {
            $result = Invoke-GitPublish -Name $repo.Name -RepoPath $repo.RepoPath -CommitMessage $repo.CommitMessage -RemoteName $GitRemote
            $runManifest.pushResults += @([ordered]@{
                name = $result.name
                repoPath = $result.repoPath
                remote = $result.remote
                branch = $result.branch
                commitMessage = $result.commitMessage
                status = $result.status
                commit = $result.commit
            })
        }
    }

    $runManifest | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $runDir 'unified_daily_update_run.json') -Encoding utf8
    $runManifest | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $latestDir 'unified_daily_update_latest.json') -Encoding utf8
}
finally {
    Pop-Location
}