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

if ([string]::IsNullOrWhiteSpace($Date)) {
    $Date = (Get-Date).ToString('yyyy-MM-dd')
}

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
$workspaceRoot = Split-Path -Parent $repoRoot
$season = ($Date -split '-')[0]
$runStamp = (Get-Date).ToString('yyyyMMdd_HHmmss')
$runDir = Join-Path $repoRoot (Join-Path 'reports\daily_update' (Join-Path $Date $runStamp))
$latestDir = Join-Path $repoRoot 'reports\daily_update\latest'
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
New-Item -ItemType Directory -Path $latestDir -Force | Out-Null

$runtimePolicy = [ordered]@{
    MLB = [ordered]@{
        simsPerGame = 1000
        workers = 4
    }
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

$runtimePolicy.MLB.workers = Get-ReasonableWorkerCount -Requested $runtimePolicy.MLB.workers
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
        $envSummary = @(
            $EnvironmentOverrides.GetEnumerator() |
                Sort-Object Name |
                ForEach-Object {
                    $displayValue = if ($_.Key -match '(^|_)(KEY|TOKEN|SECRET)(_|$)') { '<redacted>' } else { $_.Value }
                    "{0}={1}" -f $_.Key, $displayValue
                }
        ) -join '; '
        Write-Host "    env: $envSummary" -ForegroundColor DarkGray
    }

    if ($DryRun) {
        return
    }

    Push-Location $WorkingDirectory
    $previousEnv = @{}
    $hadNativeErrorPreference = $false
    $priorNativeErrorPreference = $null
    try {
        if ($EnvironmentOverrides) {
            foreach ($entry in $EnvironmentOverrides.GetEnumerator()) {
                $previousEnv[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, 'Process')
                [Environment]::SetEnvironmentVariable($entry.Key, [string]$entry.Value, 'Process')
            }
        }

        if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Global -ErrorAction SilentlyContinue) {
            $hadNativeErrorPreference = $true
            $priorNativeErrorPreference = $Global:PSNativeCommandUseErrorActionPreference
            $Global:PSNativeCommandUseErrorActionPreference = $false
        }

        $resolvedCommand = $Command[0]
        $commandInfo = Get-Command -Name $Command[0] -ErrorAction SilentlyContinue
        if ($commandInfo -and -not [string]::IsNullOrWhiteSpace($commandInfo.Source)) {
            $resolvedCommand = $commandInfo.Source
        }
        $argumentList = @()
        if ($Command.Length -gt 1) {
            $argumentList = $Command[1..($Command.Length - 1)]
        }

        # Run in the current terminal so command output is visible as it happens.
        $process = Start-Process -FilePath $resolvedCommand -ArgumentList $argumentList -WorkingDirectory $WorkingDirectory -NoNewWindow -PassThru
        Write-Host ("    pid: {0}" -f $process.Id) -ForegroundColor DarkGray
        $pollIntervalMs = 15000
        while (-not $process.WaitForExit($pollIntervalMs)) {
            $elapsed = (Get-Date) - $process.StartTime
            Write-Host ("    ... still running ({0:hh\\:mm\\:ss})" -f $elapsed) -ForegroundColor DarkGray
        }

        $LASTEXITCODE = $process.ExitCode
        if ($process.ExitCode -ne 0) {
            throw "$Name failed with exit code $($process.ExitCode)"
        }
    }
    finally {
        if ($hadNativeErrorPreference) {
            $Global:PSNativeCommandUseErrorActionPreference = $priorNativeErrorPreference
        }
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

    if (Test-PythonExecutable -Executable 'py') {
        return 'py'
    }

    if (Test-PythonExecutable -Executable 'python') {
        return 'python'
    }

    throw 'Unable to find a working Python executable. Checked virtual environments, local installs, py launcher, and python on PATH.'
}

function Resolve-WorkspaceRepoPath {
    param([string]$RepoName)

    if ([string]::IsNullOrWhiteSpace($RepoName)) {
        return $null
    }

    $candidate = Join-Path $workspaceRoot $RepoName
    if (Test-Path $candidate) {
        return $candidate
    }
    return $null
}

function Resolve-VendoredRepoPath {
    param([string]$RelativePath)

    if ([string]::IsNullOrWhiteSpace($RelativePath)) {
        return $null
    }

    $candidate = Join-Path $repoRoot $RelativePath
    if (Test-Path $candidate) {
        return $candidate
    }
    return $null
}

function Get-MirrorManifestPath {
    param(
        [string]$Sport,
        [string]$DateValue
    )

    if ([string]::IsNullOrWhiteSpace($Sport) -or [string]::IsNullOrWhiteSpace($DateValue)) {
        return $null
    }

    $slug = $Sport.Trim().ToLowerInvariant()
    return Join-Path $repoRoot (Join-Path ("data\{0}_source\manifests" -f $slug) ("mirror_refresh_{0}.json" -f $DateValue))
}

function Get-SportPolicySnapshot {
    param([string]$Sport)

    if ([string]::IsNullOrWhiteSpace($Sport)) {
        return $null
    }

    $sportKey = $Sport.Trim().ToUpperInvariant()
    if (-not $runtimePolicy.Contains($sportKey)) {
        return $null
    }
    return $runtimePolicy[$sportKey]
}

function Get-ProcessEnvValue {
    param([string[]]$Names)

    foreach ($name in $Names) {
        if ([string]::IsNullOrWhiteSpace($name)) {
            continue
        }
        $scopes = @('Process', 'User', 'Machine')
        foreach ($scope in $scopes) {
            $value = [Environment]::GetEnvironmentVariable($name, $scope)
            if (-not [string]::IsNullOrWhiteSpace($value)) {
                return $value
            }
        }
    }
    return $null
}

function Import-EnvFile {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path $Path)) {
        return @()
    }

    $imported = @()
    foreach ($rawLine in Get-Content -Path $Path) {
        $line = [string]$rawLine
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        $trimmed = $line.Trim()
        if ($trimmed.StartsWith('#')) {
            continue
        }
        if ($trimmed.StartsWith('export ')) {
            $trimmed = $trimmed.Substring(7).Trim()
        }

        $separatorIndex = $trimmed.IndexOf('=')
        if ($separatorIndex -le 0) {
            continue
        }

        $name = $trimmed.Substring(0, $separatorIndex).Trim()
        if ([string]::IsNullOrWhiteSpace($name)) {
            continue
        }
        if (Get-ProcessEnvValue -Names @($name)) {
            continue
        }

        $value = $trimmed.Substring($separatorIndex + 1).Trim()
        if ($value.Length -ge 2) {
            $quotePair = $value.Substring(0, 1) + $value.Substring($value.Length - 1, 1)
            if ($quotePair -eq '""' -or $quotePair -eq "''") {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }

        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        $imported += $name
    }

    return $imported
}

function Import-RepoEnvFiles {
    param([string]$RepoPath)

    $envCandidates = @(
        (Join-Path $RepoPath '.env'),
        (Join-Path $RepoPath '.env.local')
    )
    $imported = @()
    foreach ($candidate in $envCandidates) {
        $imported += @(Import-EnvFile -Path $candidate)
    }
    return @($imported | Select-Object -Unique)
}

$importedEnvNames = @(Import-RepoEnvFiles -RepoPath $repoRoot)
if ($importedEnvNames.Count -gt 0) {
    Write-Host ("Loaded repo env values into process scope: " + ($importedEnvNames -join ', ')) -ForegroundColor DarkGray
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

function Get-ForcedPublishArtifactPaths {
    param(
        [string]$RepoPath,
        [string]$DateValue,
        [bool]$SkipMLB,
        [bool]$SkipNBA,
        [bool]$SkipNHL,
        [bool]$SkipWNBA,
        [bool]$SkipNCAAB
    )

    $paths = New-Object System.Collections.Generic.List[string]
    $dateSlug = $DateValue -replace '-', '_'

    function Add-PathIfPresent {
        param([string]$RelativePath)

        if ([string]::IsNullOrWhiteSpace($RelativePath)) {
            return
        }

        $fullPath = Join-Path $RepoPath $RelativePath
        if (Test-Path $fullPath) {
            $paths.Add($RelativePath) | Out-Null
        }
    }

    function Add-PathsByPattern {
        param([string]$RelativePattern)

        if ([string]::IsNullOrWhiteSpace($RelativePattern)) {
            return
        }

        $fullPattern = Join-Path $RepoPath $RelativePattern
        foreach ($match in @(Get-ChildItem -Path $fullPattern -File -ErrorAction SilentlyContinue)) {
            $relativePath = $match.FullName.Substring($RepoPath.Length).TrimStart('\', '/') -replace '\\', '/'
            if (-not [string]::IsNullOrWhiteSpace($relativePath)) {
                $paths.Add($relativePath) | Out-Null
            }
        }
    }

    function Add-PathsUnderRoot {
        param([string]$RelativeRoot)

        if ([string]::IsNullOrWhiteSpace($RelativeRoot)) {
            return
        }

        $fullRoot = Join-Path $RepoPath $RelativeRoot
        if (-not (Test-Path $fullRoot)) {
            return
        }

        foreach ($match in @(Get-ChildItem -Path $fullRoot -File -Recurse -ErrorAction SilentlyContinue)) {
            $relativePath = $match.FullName.Substring($RepoPath.Length).TrimStart('\', '/') -replace '\\', '/'
            if (-not [string]::IsNullOrWhiteSpace($relativePath)) {
                $paths.Add($relativePath) | Out-Null
            }
        }
    }

    if (-not $SkipMLB) {
        foreach ($relativePath in @(
            "data/mlb_source/data/daily/daily_summary_${dateSlug}.json",
            "data/mlb_source/data/daily/daily_summary_${dateSlug}_profile_bundle.json",
            "data/mlb_source/data/daily/daily_summary_${dateSlug}_locked_policy.json",
            "data/mlb_source/data/daily/daily_summary_${dateSlug}_hr_targets.json",
            "data/mlb_source/data/daily/daily_summary_${dateSlug}_rfi_targets.json",
            "data/mlb_source/data/daily/ladders/daily_ladders_${dateSlug}.json",
            "data/mlb_source/data/daily/top_props/daily_top_props_${dateSlug}.json",
            "data/mlb_source/data/daily/ops/daily_ops_${dateSlug}.json",
            "data/mlb_source/data/daily/snapshots/${DateValue}/lineups.json",
            "data/mlb_source/data/daily/snapshots/${DateValue}/probables.json",
            "data/mlb_source/data/daily/snapshots/${DateValue}/oddsapi_game_lines_${dateSlug}.json",
            "data/mlb_source/data/daily/snapshots/${DateValue}/oddsapi_pitcher_props_${dateSlug}.json",
            "data/mlb_source/data/daily/snapshots/${DateValue}/oddsapi_hitter_props_${dateSlug}.json",
            "data/mlb_source/data/live_lens/live_lens_${dateSlug}.jsonl",
            "data/mlb_source/data/live_lens/live_lens_report_${dateSlug}.json",
            "data/mlb_source/data/live_lens/render_sync/live_lens_reports_${dateSlug}.json",
            "data/mlb_source/data/live_lens/prop_registry/live_prop_registry_${dateSlug}.json",
            "data/mlb_source/data/live_lens/prop_registry/live_prop_registry_${dateSlug}.jsonl",
            "data/mlb_source/data/live_lens/prop_registry/live_prop_observations_${dateSlug}.jsonl"
        )) {
            Add-PathIfPresent -RelativePath $relativePath
        }

        Add-PathsByPattern -RelativePattern "data/mlb_source/data/daily/sims/${DateValue}/sim_*.json"
        Add-PathsByPattern -RelativePattern "data/mlb_source/data/daily/season_frontend/season_manifest_*_${dateSlug}.json"
        Add-PathsByPattern -RelativePattern "data/mlb_source/data/daily/season_frontend/season_day_*_${dateSlug}_*.json"
        Add-PathsByPattern -RelativePattern "data/mlb_source/data/daily/season_frontend/season_betting_day_*_${dateSlug}_*.json"
        Add-PathsByPattern -RelativePattern "data/mlb_source/data/daily/season_frontend/season_official_betting_day_*_${dateSlug}_*.json"
    }

    if (-not $SkipNBA) {
        foreach ($relativePath in @(
            "data/nba_source/data/processed/game_cards_${DateValue}.csv",
            "data/nba_source/data/processed/recommendations_${DateValue}.csv",
            "data/nba_source/data/processed/recommendations_slate_${DateValue}.json",
            "data/nba_source/data/processed/cards_sim_detail_${DateValue}.json",
            "data/nba_source/data/processed/cards_props_snapshot_${DateValue}.json",
            "data/nba_source/data/processed/props_recommendations_top_by_game_${DateValue}.json",
            "data/nba_source/data/processed/oddsapi_player_props_${DateValue}.csv",
            "data/nba_source/data/processed/props_predictions_${DateValue}.csv",
            "data/nba_source/data/processed/props_edges_${DateValue}.csv",
            "data/nba_source/data/processed/props_recommendations_${DateValue}.csv",
            "data/nba_source/data/processed/recon_games_${DateValue}.csv",
            "data/nba_source/data/processed/recon_quarters_${DateValue}.csv",
            "data/nba_source/data/processed/recon_props_${DateValue}.csv",
            "data/nba_source/data/processed/recon_players_${DateValue}.csv",
            "data/nba_source/data/processed/live_player_lens_tuning_${DateValue}.csv",
            "data/nba_source/data/processed/boxscores_${DateValue}.csv",
            "data/nba_source/data/processed/live_lens_projections_${DateValue}.jsonl",
            "data/nba_source/data/processed/live_lens_signals_${DateValue}.jsonl",
            "data/nba_source/data/processed/live_snapshots/live_state_${DateValue}.jsonl",
            "data/nba_source/data/processed/live_snapshots/live_lines_${DateValue}.jsonl",
            "data/nba_source/data/processed/live_snapshots/live_pbp_stats_${DateValue}.jsonl",
            "data/nba_source/data/processed/live_snapshots/live_player_boxscore_${DateValue}.jsonl",
            "data/nba_source/data/processed/live_snapshots/live_player_lens_${DateValue}.jsonl",
            "data/nba_source/data/live_lens/live_lens_projections_${DateValue}.jsonl",
            "data/nba_source/data/live_lens/live_lens_signals_${DateValue}.jsonl"
        )) {
            Add-PathIfPresent -RelativePath $relativePath
        }

        Add-PathsByPattern -RelativePattern "data/nba_source/data/processed/smart_sim_${DateValue}_*.json"
        Add-PathsByPattern -RelativePattern "data/nba_source/data/processed/season_betting_card_manifest_*_retuned_${DateValue}.json"
        Add-PathsByPattern -RelativePattern "data/nba_source/data/processed/season_betting_card_manifest_*_retuned.json"
        Add-PathsByPattern -RelativePattern "data/nba_source/data/processed/season_betting_card_day_*_retuned_${DateValue}.json"
        Add-PathsByPattern -RelativePattern "data/nba_source/data/processed/season_betting_card_day_*_retuned_${DateValue}_insights.json"
    }

    if (-not $SkipWNBA) {
        foreach ($relativePath in @(
            "data/wnba_source/data/processed/game_cards_${DateValue}.csv",
            "data/wnba_source/data/processed/recommendations_${DateValue}.csv",
            "data/wnba_source/data/processed/recommendations_slate_${DateValue}.json",
            "data/wnba_source/data/processed/cards_sim_detail_${DateValue}.json",
            "data/wnba_source/data/processed/cards_props_snapshot_${DateValue}.json",
            "data/wnba_source/data/processed/props_recommendations_top_by_game_${DateValue}.json",
            "data/wnba_source/data/processed/oddsapi_player_props_${DateValue}.csv",
            "data/wnba_source/data/processed/props_predictions_${DateValue}.csv",
            "data/wnba_source/data/processed/props_edges_${DateValue}.csv",
            "data/wnba_source/data/processed/props_recommendations_${DateValue}.csv",
            "data/wnba_source/data/processed/recon_games_${DateValue}.csv",
            "data/wnba_source/data/processed/recon_quarters_${DateValue}.csv",
            "data/wnba_source/data/processed/recon_props_${DateValue}.csv",
            "data/wnba_source/data/processed/recon_players_${DateValue}.csv",
            "data/wnba_source/data/processed/live_player_lens_tuning_${DateValue}.csv",
            "data/wnba_source/data/processed/boxscores_${DateValue}.csv",
            "data/wnba_source/data/processed/live_lens_projections_${DateValue}.jsonl",
            "data/wnba_source/data/processed/live_lens_signals_${DateValue}.jsonl",
            "data/wnba_source/data/processed/live_snapshots/live_state_${DateValue}.jsonl",
            "data/wnba_source/data/processed/live_snapshots/live_lines_${DateValue}.jsonl",
            "data/wnba_source/data/processed/live_snapshots/live_pbp_stats_${DateValue}.jsonl",
            "data/wnba_source/data/processed/live_snapshots/live_player_boxscore_${DateValue}.jsonl",
            "data/wnba_source/data/processed/live_snapshots/live_player_lens_${DateValue}.jsonl",
            "data/wnba_source/data/live_lens/live_lens_projections_${DateValue}.jsonl",
            "data/wnba_source/data/live_lens/live_lens_signals_${DateValue}.jsonl"
        )) {
            Add-PathIfPresent -RelativePath $relativePath
        }

        Add-PathsByPattern -RelativePattern "data/wnba_source/data/processed/smart_sim_${DateValue}_*.json"
    }

    if (-not $SkipNHL) {
        foreach ($relativePath in @(
            "data/nhl_source/data/processed/predictions_${DateValue}.csv",
            "data/nhl_source/data/processed/predictions_sim_${DateValue}.csv",
            "data/nhl_source/data/processed/recommendations_${DateValue}.csv",
            "data/nhl_source/data/processed/recommendations_sim_${DateValue}.csv",
            "data/nhl_source/data/processed/reconciliations_log.csv",
            "data/nhl_source/data/processed/props_reconciliations_log.csv",
            "data/nhl_source/data/processed/recon_games_${DateValue}.csv",
            "data/nhl_source/data/processed/recon_props_${DateValue}.csv",
            "data/nhl_source/data/processed/props_boxscores_sim_${DateValue}.csv",
            "data/nhl_source/data/processed/props_boxscores_sim_hist_${DateValue}.csv",
            "data/nhl_source/data/processed/props_recommendations_${DateValue}.csv",
            "data/nhl_source/data/processed/roster_snapshot_${DateValue}.csv",
            "data/nhl_source/data/processed/lineups_${DateValue}.csv",
            "data/nhl_source/data/processed/lineups_co_toi_${DateValue}.csv",
            "data/nhl_source/data/processed/live_lens_projections_${DateValue}.jsonl",
            "data/nhl_source/data/processed/live_lens_signals_${DateValue}.jsonl",
            "data/nhl_source/data/live_lens/live_lens_projections_${DateValue}.jsonl",
            "data/nhl_source/data/live_lens/live_lens_signals_${DateValue}.jsonl",
            "data/nhl_source/data/odds/games/date=${DateValue}/scoreboard.csv",
            "data/nhl_source/data/odds/team/date=${DateValue}/oddsapi.csv",
            "data/nhl_source/data/odds/team/date=${DateValue}/oddsapi.parquet",
            "data/nhl_source/data/props/player_props_lines/date=${DateValue}/oddsapi.csv",
            "data/nhl_source/data/props/player_props_lines/date=${DateValue}/oddsapi.parquet"
        )) {
            Add-PathIfPresent -RelativePath $relativePath
        }
    }

    if (-not $SkipNCAAB) {
        foreach ($relativePath in @(
            "data/ncaab_source/api/recommendations/recommendations_${DateValue}.json",
            "data/ncaab_source/api/live_state/live_state_${DateValue}.json",
            "data/ncaab_source/api/live_lines/live_lines_${DateValue}.json"
        )) {
            Add-PathIfPresent -RelativePath $relativePath
        }
    }

    return @($paths | Select-Object -Unique)
}

function Invoke-GitPublish {
    param(
        [string]$Name,
        [string]$RepoPath,
        [string]$CommitMessage,
        [string]$RemoteName,
        [string[]]$ForceIncludePaths = @()
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

        $defaultExcludeRegexes = @(
            '^Syndicate\.code-workspace$',
            '^data/[^/]+_source/manifests/mirror_refresh.*\.json$',
            '^vendor/[^/]+/data/processed/\.cron_meta\.json$'
        )
        $stagedPaths = @(& git diff --cached --name-only --relative)
        if ($LASTEXITCODE -ne 0) {
            throw "git diff --cached failed for $RepoPath with exit code $LASTEXITCODE"
        }
        foreach ($stagedPath in $stagedPaths) {
            if ([string]::IsNullOrWhiteSpace($stagedPath)) {
                continue
            }
            $shouldExclude = $false
            foreach ($excludeRegex in $defaultExcludeRegexes) {
                if ($stagedPath -match $excludeRegex) {
                    $shouldExclude = $true
                    break
                }
            }
            if (-not $shouldExclude) {
                continue
            }
            & git restore --staged -- $stagedPath
            if ($LASTEXITCODE -ne 0) {
                throw "git restore --staged failed for $RepoPath path $stagedPath with exit code $LASTEXITCODE"
            }
        }

        foreach ($relativePath in @($ForceIncludePaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
            & git add -f -- $relativePath
            if ($LASTEXITCODE -ne 0) {
                throw "git add -f failed for $RepoPath path $relativePath with exit code $LASTEXITCODE"
            }
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
$preferLocalMirrorArtifactsForGate = $false
$forcedPublishArtifactPaths = Get-ForcedPublishArtifactPaths -RepoPath $repoRoot -DateValue $Date -SkipMLB ([bool]$SkipMLB) -SkipNBA ([bool]$SkipNBA) -SkipNHL ([bool]$SkipNHL) -SkipWNBA ([bool]$SkipWNBA) -SkipNCAAB ([bool]$SkipNCAAB)
$sharedOddsApiKey = Get-ProcessEnvValue -Names @('ODDS_API_KEY', 'ODDSAPI_KEY', 'THEODDS_API_KEY', 'THEODDSAPI_KEY', 'NCAAB_THEODDS_API_KEY')
$ncaabOddsApiKey = Get-ProcessEnvValue -Names @('NCAAB_THEODDS_API_KEY', 'THEODDSAPI_KEY', 'THEODDS_API_KEY')

if (-not $SkipMLB) {
    $mlbVendoredRoot = Resolve-VendoredRepoPath -RelativePath 'vendor\mlb_bettingv2'
    $mlbVendoredDailyUpdate = if ($mlbVendoredRoot) { Join-Path $mlbVendoredRoot 'tools\daily_update.py' } else { $null }
    if (-not ($mlbVendoredDailyUpdate -and (Test-Path $mlbVendoredDailyUpdate))) {
        throw "MLB self-contained daily update is unavailable because vendor\\mlb_bettingv2\\tools\\daily_update.py was not found. The fallback Syndicate MLB refresh only materializes existing artifacts and is not equivalent to the full ui-daily workflow."
    }

    $preferLocalMirrorArtifactsForGate = $true
    $mlbArtifactDataRoot = Join-Path $repoRoot 'data\mlb_source\source_artifacts\data'
    $mlbOddsApiKey = Get-ProcessEnvValue -Names @('ODDS_API_KEY', 'ODDSAPI_KEY', 'THEODDS_API_KEY', 'THEODDSAPI_KEY', 'NCAAB_THEODDS_API_KEY')
    $mlbEnvOverrides = @{
        MLB_BETTING_DATA_ROOT = $mlbArtifactDataRoot
        MLB_LIVE_LENS_DIR = (Join-Path $mlbArtifactDataRoot 'live_lens')
    }
    if (-not [string]::IsNullOrWhiteSpace($mlbOddsApiKey)) {
        $mlbEnvOverrides.ODDS_API_KEY = $mlbOddsApiKey
    }
    $sourceSteps += [pscustomobject]@{
        Sport = 'mlb'
        Name = 'MLB vendored daily update'
        Workflow = 'vendored_daily_update'
        Command = @(
            (Resolve-Python $repoRoot),
            'tools\daily_update.py',
            '--workflow', 'ui-daily',
            '--date', $Date,
            '--season', $season,
            '--sims', [string]$runtimePolicy.MLB.simsPerGame,
            '--workers', [string]$runtimePolicy.MLB.workers,
            '--git-push', 'off',
            '--validate-render-frontend', 'off',
            '--build-next-day', 'on'
        )
        WorkingDirectory = $mlbVendoredRoot
        EnvironmentOverrides = $mlbEnvOverrides
        RuntimePolicy = $runtimePolicy.MLB
    }
    $sourceSteps += [pscustomobject]@{
        Sport = 'mlb'
        Name = 'MLB current-day live-lens refresh'
        Workflow = 'syndicate_refresh'
        Command = @(
            (Resolve-Python $repoRoot),
            'scripts\refresh_mlb_oddsapi.py',
            '--date', $Date,
            '--source-root', 'data\mlb_source\source_artifacts',
            '--artifact-root', 'data\mlb_source',
            '--overwrite', 'off'
        )
        WorkingDirectory = $repoRoot
        EnvironmentOverrides = $mlbEnvOverrides
        RuntimePolicy = $runtimePolicy.MLB
    }
}
if (-not $SkipNBA) {
    $nbaVendoredRoot = Resolve-VendoredRepoPath -RelativePath 'vendor\nba_betting_repo'
    $nbaVendoredApp = if ($nbaVendoredRoot) { Join-Path $nbaVendoredRoot 'app.py' } else { $null }
    if (-not ($nbaVendoredApp -and (Test-Path $nbaVendoredApp))) {
        throw "NBA self-contained refresh is unavailable because vendor\\nba_betting_repo\\app.py was not found. The fallback NBA Syndicate props refresh still requires a source-root for fresh runs and is not a self-contained replacement."
    }

    $preferLocalMirrorArtifactsForGate = $true
    $nbaEnvOverrides = @{
        REFRESH_PREDICT_PROPS_SMART_SIM_N_SIMS = [string]$runtimePolicy.NBA.smartsimNSims
        REFRESH_PREDICT_PROPS_SMART_SIM_WORKERS = [string]$runtimePolicy.NBA.smartsimWorkers
    }
    if (-not [string]::IsNullOrWhiteSpace($sharedOddsApiKey)) {
        $nbaEnvOverrides.ODDS_API_KEY = $sharedOddsApiKey
    }
    $sourceSteps += [pscustomobject]@{
        Sport = 'nba'
        Name = 'NBA vendored daily update'
        Workflow = 'vendored_daily_update'
        Command = @(
            (Resolve-Python $repoRoot),
            'scripts\refresh_nba_oddsapi_props.py',
            '--date', $Date,
            '--source-root', 'vendor\nba_betting_repo',
            '--artifact-root', 'data\nba_source',
            '--log-file', (Join-Path $runDir 'nba_props_refresh.log'),
            '--force-refresh',
            '--days-ahead', '0',
            '--do-edges',
            '--do-export'
        )
        WorkingDirectory = $repoRoot
        EnvironmentOverrides = $nbaEnvOverrides
        RuntimePolicy = $runtimePolicy.NBA
    }
}
if (-not $SkipWNBA) {
    $wnbaVendoredRoot = Resolve-VendoredRepoPath -RelativePath 'vendor\wnba_betting_repo'
    $wnbaVendoredApp = if ($wnbaVendoredRoot) { Join-Path $wnbaVendoredRoot 'app.py' } else { $null }
    if (-not ($wnbaVendoredApp -and (Test-Path $wnbaVendoredApp))) {
        throw "WNBA self-contained refresh is unavailable because vendor\\wnba_betting_repo\\app.py was not found. The fallback WNBA Syndicate props refresh still requires a source-root for fresh runs and is not a self-contained replacement."
    }

    $preferLocalMirrorArtifactsForGate = $true
    $wnbaEnvOverrides = @{
        REFRESH_PREDICT_PROPS_SMART_SIM_N_SIMS = [string]$runtimePolicy.WNBA.smartsimNSims
        REFRESH_PREDICT_PROPS_SMART_SIM_WORKERS = [string]$runtimePolicy.WNBA.smartsimWorkers
    }
    if (-not [string]::IsNullOrWhiteSpace($sharedOddsApiKey)) {
        $wnbaEnvOverrides.ODDS_API_KEY = $sharedOddsApiKey
    }
    $sourceSteps += [pscustomobject]@{
        Sport = 'wnba'
        Name = 'WNBA vendored daily update'
        Workflow = 'vendored_daily_update'
        Command = @(
            (Resolve-Python $repoRoot),
            'scripts\refresh_wnba_oddsapi_props.py',
            '--date', $Date,
            '--source-root', 'vendor\wnba_betting_repo',
            '--artifact-root', 'data\wnba_source',
            '--log-file', (Join-Path $runDir 'wnba_props_refresh.log'),
            '--force-refresh',
            '--days-ahead', '0',
            '--do-edges',
            '--do-export'
        )
        WorkingDirectory = $repoRoot
        EnvironmentOverrides = $wnbaEnvOverrides
        RuntimePolicy = $runtimePolicy.WNBA
    }
}
if (-not $SkipNHL) {
    $nhlVendoredRoot = Resolve-VendoredRepoPath -RelativePath 'vendor\nhl_betting_repo'
    $nhlVendoredCli = if ($nhlVendoredRoot) { Join-Path $nhlVendoredRoot 'nhl_betting\cli.py' } else { $null }
    if ($nhlVendoredCli -and (Test-Path $nhlVendoredCli)) {
        $preferLocalMirrorArtifactsForGate = $true
        $nhlEnvOverrides = @{}
        if (-not [string]::IsNullOrWhiteSpace($sharedOddsApiKey)) {
            $nhlEnvOverrides.ODDS_API_KEY = $sharedOddsApiKey
        }
        $sourceSteps += [pscustomobject]@{
            Sport = 'nhl'
            Name = 'NHL vendored daily update'
            Workflow = 'vendored_daily_update'
            Command = @(
                (Resolve-Python $repoRoot),
                'scripts\refresh_nhl_oddsapi.py',
                '--date', $Date,
                '--source-root', 'vendor\nhl_betting_repo',
                '--artifact-root', 'data\nhl_source\source_artifacts',
                '--days-ahead', '1',
                '--props-boxscore-n-sims', [string]$runtimePolicy.NHL.propsBoxscoreNSims
            )
            WorkingDirectory = $repoRoot
            EnvironmentOverrides = $nhlEnvOverrides
            RuntimePolicy = $runtimePolicy.NHL
        }
    }
    else {
        $nhlEnvOverrides = @{}
        if (-not [string]::IsNullOrWhiteSpace($sharedOddsApiKey)) {
            $nhlEnvOverrides.ODDS_API_KEY = $sharedOddsApiKey
        }
        $sourceSteps += [pscustomobject]@{
            Sport = 'nhl'
            Name = 'NHL local odds refresh'
            Workflow = 'syndicate_refresh'
            Command = @(
                (Resolve-Python $repoRoot),
                'scripts\refresh_nhl_oddsapi.py',
                '--date', $Date,
                '--days-ahead', '1',
                '--artifact-root', 'data\nhl_source\source_artifacts'
            )
            WorkingDirectory = $repoRoot
            EnvironmentOverrides = $nhlEnvOverrides
            RuntimePolicy = $runtimePolicy.NHL
        }
    }
}
if (-not $SkipNFL) {
    $nflEnvOverrides = @{}
    if (-not [string]::IsNullOrWhiteSpace($sharedOddsApiKey)) {
        $nflEnvOverrides.ODDS_API_KEY = $sharedOddsApiKey
    }
    $sourceSteps += [pscustomobject]@{
        Name = 'NFL local odds refresh'
        Command = @(
            (Resolve-Python $repoRoot),
            'scripts\refresh_nfl_oddsapi.py',
            '--artifact-root', 'data\nfl_source\source_artifacts'
        )
        WorkingDirectory = $repoRoot
        EnvironmentOverrides = $nflEnvOverrides
    }
}
if (-not $SkipNCAAF) {
    $ncaafEnvOverrides = @{}
    if (-not [string]::IsNullOrWhiteSpace($sharedOddsApiKey)) {
        $ncaafEnvOverrides.ODDS_API_KEY = $sharedOddsApiKey
    }
    $ncaafSourceRoot = [Environment]::GetEnvironmentVariable('SYNDICATE_SOURCE_ROOT_NCAAF')
    if ([string]::IsNullOrWhiteSpace($ncaafSourceRoot)) {
        $ncaafSourceRoot = Resolve-WorkspaceRepoPath 'NCAAFCompare'
    }
    if ([string]::IsNullOrWhiteSpace($ncaafSourceRoot) -or (-not (Test-Path $ncaafSourceRoot))) {
        throw 'NCAAF local odds refresh requires a usable source root. Set SYNDICATE_SOURCE_ROOT_NCAAF or open the NCAAFCompare workspace repo.'
    }
    $sourceSteps += [pscustomobject]@{
        Name = 'NCAAF local odds refresh'
        Command = @(
            (Resolve-Python $repoRoot),
            'scripts\refresh_ncaaf_oddsapi.py',
            '--source-root', $ncaafSourceRoot,
            '--artifact-root', 'data\ncaaf_source\source_artifacts'
        )
        WorkingDirectory = $repoRoot
        EnvironmentOverrides = $ncaafEnvOverrides
    }
}
if (-not $SkipNCAAB) {
    $ncaabRawOutputsRoot = Join-Path $repoRoot 'data\ncaab_source\raw_outputs'
    $ncaabApiKey = $ncaabOddsApiKey
    if (-not [string]::IsNullOrWhiteSpace($ncaabApiKey)) {
        $sourceSteps += [pscustomobject]@{
            Name = 'NCAAB Syndicate odds refresh'
            Command = @(
                (Resolve-Python $repoRoot),
                'scripts\refresh_ncaab_odds_history.py',
                '--date', $Date,
                '--out-dir', (Join-Path 'data\ncaab_source\raw_outputs\by_date' $Date)
            )
            WorkingDirectory = $repoRoot
            EnvironmentOverrides = @{ NCAAB_THEODDS_API_KEY = $ncaabApiKey }
        }
    }
    elseif (-not (Test-Path $ncaabRawOutputsRoot)) {
        throw "NCAAB raw outputs not found at $ncaabRawOutputsRoot and no NCAAB/TheOddsAPI key is available for a local refresh."
    }
}

$publishRepos += [pscustomobject]@{ Name = 'Syndicate'; RepoPath = $repoRoot; CommitMessage = "$CommitMessagePrefix $Date (Syndicate mirror + gate)" }

$runManifest = [ordered]@{
    date = $Date
    generatedAt = (Get-Date).ToString('o')
    runDir = $runDir
    latestDir = $latestDir
    runtimePolicy = $runtimePolicy
    sourceSteps = @($sourceSteps | ForEach-Object { [ordered]@{ sport = $_.Sport; workflow = $_.Workflow; name = $_.Name; workingDirectory = $_.WorkingDirectory; environmentOverrides = $_.EnvironmentOverrides; runtimePolicy = $_.RuntimePolicy; command = $_.Command } })
    sportRuns = @()
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
    refreshGate = [ordered]@{
        requested = [bool](-not $SkipRefreshGate)
        manifestPath = (Join-Path $runDir 'migration\refresh_status_manifest.json')
        runSummaryPath = (Join-Path $runDir 'migration\refresh_and_gate_run.json')
    }
    pushResults = @()
}

Push-Location $repoRoot
try {
    if ($SkipRefreshGate -and -not $SkipGitPush) {
        throw 'Cannot push git updates when -SkipRefreshGate is set. Run the gate or pass -SkipGitPush.'
    }

    if (-not $SkipGitPush) {
        foreach ($repo in $publishRepos) {
            $result = Invoke-GitPublish -Name $repo.Name -RepoPath $repo.RepoPath -CommitMessage "$CommitMessagePrefix $Date (pre-source publish)" -RemoteName $GitRemote -ForceIncludePaths $forcedPublishArtifactPaths
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

    if (-not $SkipSourceUpdates) {
        foreach ($step in $sourceSteps) {
            $startedAt = (Get-Date).ToString('o')
            $sportRun = [ordered]@{
                sport = $step.Sport
                workflow = $step.Workflow
                name = $step.Name
                startedAt = $startedAt
                completedAt = $null
                status = if ($DryRun) { 'dry_run' } else { 'started' }
                workingDirectory = $step.WorkingDirectory
                environmentOverrides = $step.EnvironmentOverrides
                runtimePolicy = $step.RuntimePolicy
                command = $step.Command
                mirrorManifestPath = (Get-MirrorManifestPath -Sport $step.Sport -DateValue $Date)
                mirrorManifestExists = $false
            }
            try {
                Invoke-Step -Name $step.Name -Command $step.Command -WorkingDirectory $step.WorkingDirectory -EnvironmentOverrides $step.EnvironmentOverrides
                $sportRun.status = if ($DryRun) { 'dry_run' } else { 'ok' }
            }
            catch {
                $sportRun.status = 'error'
                $sportRun.error = $_.Exception.Message
                $sportRun.completedAt = (Get-Date).ToString('o')
                $runManifest.sportRuns += @([pscustomobject]$sportRun)
                throw
            }
            $sportRun.completedAt = (Get-Date).ToString('o')
            $runManifest.sportRuns += @([pscustomobject]$sportRun)

            if (-not $SkipGitPush) {
                foreach ($repo in $publishRepos) {
                    $result = Invoke-GitPublish -Name $repo.Name -RepoPath $repo.RepoPath -CommitMessage "$CommitMessagePrefix $Date [$($step.Name)]" -RemoteName $GitRemote -ForceIncludePaths $forcedPublishArtifactPaths
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
        $refreshEnvOverrides = @{}
        if ($preferLocalMirrorArtifactsForGate) {
            $refreshEnvOverrides.SYNDICATE_USE_LOCAL_ARTIFACT_MIRRORS = '1'
        }
        Invoke-Step -Name 'Syndicate refresh and gate' -Command $refreshArgs -WorkingDirectory $repoRoot -EnvironmentOverrides $refreshEnvOverrides
        $runManifest.refreshGate.status = if ($DryRun) { 'dry_run' } else { 'ok' }
    }
    else {
        $runManifest.refreshGate.status = 'skipped'
    }

    foreach ($sportRun in @($runManifest.sportRuns)) {
        $mirrorManifestPath = [string]$sportRun.mirrorManifestPath
        if (-not [string]::IsNullOrWhiteSpace($mirrorManifestPath) -and (Test-Path $mirrorManifestPath)) {
            $sportRun | Add-Member -NotePropertyName mirrorManifestExists -NotePropertyValue $true -Force
        }
        else {
            $sportRun | Add-Member -NotePropertyName mirrorManifestExists -NotePropertyValue $false -Force
        }
    }

    if (-not $SkipGitPush) {
        foreach ($repo in $publishRepos) {
            $result = Invoke-GitPublish -Name $repo.Name -RepoPath $repo.RepoPath -CommitMessage $repo.CommitMessage -RemoteName $GitRemote -ForceIncludePaths $forcedPublishArtifactPaths
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