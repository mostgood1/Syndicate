param(
    [string]$Date,
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

# Use Central Time for date calculations to match Syndicate's timezone
if ([string]::IsNullOrWhiteSpace($Date)) {
    $centralTZ = [TimeZoneInfo]::FindSystemTimeZoneById("Central Standard Time")
    $Date = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $centralTZ).ToString('yyyy-MM-dd')
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
        $pollIntervalMs = 30000
        while (-not $process.WaitForExit($pollIntervalMs)) {
            $elapsed = (Get-Date) - $process.StartTime
            Write-Host ("    ... still running ({0}s)" -f [int]$elapsed.TotalSeconds) -ForegroundColor DarkGray
        }

        # Ensure process metadata is fully updated before reading ExitCode.
        $process.WaitForExit()
        $process.Refresh()

        $exitCode = $null
        try {
            $exitCode = [int]$process.ExitCode
        }
        catch {
            $exitCode = $null
        }

        if ($null -eq $exitCode -and ($LASTEXITCODE -is [int])) {
            $exitCode = [int]$LASTEXITCODE
        }

        if ($null -eq $exitCode) {
            throw "$Name failed because the child process exit code could not be determined (pid $($process.Id))."
        }

        $LASTEXITCODE = $exitCode
        if ($exitCode -ne 0) {
            $exitCodeText = [string]$exitCode
            throw "$Name failed with exit code $exitCodeText"
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

function Test-ProcessIdRunning {
    param([int]$ProcessId)

    if ($ProcessId -le 0) {
        return $false
    }

    return [bool](Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Clear-StaleMlbUiDailyLocks {
    param(
        [string]$MlbDataRoot,
        [string]$DateValue,
        [string]$SeasonValue
    )

    if ([string]::IsNullOrWhiteSpace($MlbDataRoot) -or [string]::IsNullOrWhiteSpace($DateValue) -or [string]::IsNullOrWhiteSpace($SeasonValue)) {
        return 0
    }

    $lockDir = Join-Path $MlbDataRoot 'runtime\locks'
    if (-not (Test-Path $lockDir)) {
        return 0
    }

    $removedCount = 0
    $pattern = "daily_update_ui-daily_{0}_{1}_*.lock" -f $SeasonValue, $DateValue
    foreach ($lockFile in @(Get-ChildItem -Path $lockDir -File -Filter $pattern -ErrorAction SilentlyContinue)) {
        $lockPid = $null
        try {
            $lockPayload = Get-Content -Path $lockFile.FullName -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
            if ($null -ne $lockPayload.pid) {
                $lockPid = [int]$lockPayload.pid
            }
        }
        catch {
            $lockPid = $null
        }

        if ($null -ne $lockPid -and (Test-ProcessIdRunning -ProcessId $lockPid)) {
            Write-Host ("    lock active (pid {0}) at {1}" -f $lockPid, $lockFile.FullName) -ForegroundColor DarkGray
            continue
        }

        Remove-Item -Path $lockFile.FullName -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path $lockFile.FullName)) {
            Write-Host ("    removed stale lock: {0}" -f $lockFile.Name) -ForegroundColor Yellow
            $removedCount += 1
        }
    }

    return $removedCount
}

function Get-ActiveMlbUiDailyLockCount {
    param(
        [string]$MlbDataRoot,
        [string]$DateValue,
        [string]$SeasonValue
    )

    if ([string]::IsNullOrWhiteSpace($MlbDataRoot) -or [string]::IsNullOrWhiteSpace($DateValue) -or [string]::IsNullOrWhiteSpace($SeasonValue)) {
        return 0
    }

    $lockDir = Join-Path $MlbDataRoot 'runtime\locks'
    if (-not (Test-Path $lockDir)) {
        return 0
    }

    $activeCount = 0
    $pattern = "daily_update_ui-daily_{0}_{1}_*.lock" -f $SeasonValue, $DateValue
    foreach ($lockFile in @(Get-ChildItem -Path $lockDir -File -Filter $pattern -ErrorAction SilentlyContinue)) {
        $lockPid = $null
        try {
            $lockPayload = Get-Content -Path $lockFile.FullName -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
            if ($null -ne $lockPayload.pid) {
                $lockPid = [int]$lockPayload.pid
            }
        }
        catch {
            $lockPid = $null
        }

        if ($null -ne $lockPid -and (Test-ProcessIdRunning -ProcessId $lockPid)) {
            $activeCount += 1
        }
    }

    return $activeCount
}

function Wait-ForMlbUiDailyLockRelease {
    param(
        [string]$MlbDataRoot,
        [string]$DateValue,
        [string]$SeasonValue,
        [int]$TimeoutSeconds = 3600,
        [int]$PollSeconds = 20
    )

    if ([string]::IsNullOrWhiteSpace($MlbDataRoot) -or [string]::IsNullOrWhiteSpace($DateValue) -or [string]::IsNullOrWhiteSpace($SeasonValue)) {
        return
    }

    $safeTimeout = [Math]::Max(1, [int]$TimeoutSeconds)
    $safePoll = [Math]::Max(1, [int]$PollSeconds)
    $deadline = (Get-Date).AddSeconds($safeTimeout)

    while ($true) {
        $activeCount = Get-ActiveMlbUiDailyLockCount -MlbDataRoot $MlbDataRoot -DateValue $DateValue -SeasonValue $SeasonValue
        if ($activeCount -le 0) {
            return
        }

        $remaining = [int][Math]::Floor(($deadline - (Get-Date)).TotalSeconds)
        if ($remaining -le 0) {
            throw "MLB ui-daily lock wait timed out for $DateValue after $safeTimeout seconds; another run is still active"
        }

        Write-Host ("    waiting for MLB ui-daily lock release for {0}; active locks={1}; remaining={2}s" -f $DateValue, $activeCount, $remaining) -ForegroundColor Yellow
        Start-Sleep -Seconds ([Math]::Min($safePoll, $remaining))
    }
}

function Get-BasketballScheduledGamesCheck {
    param(
        [string]$Sport,
        [string]$DateValue
    )

    $result = [ordered]@{
        known = $false
        count = $null
        source = $null
        note = $null
    }

    if ([string]::IsNullOrWhiteSpace($Sport) -or [string]::IsNullOrWhiteSpace($DateValue)) {
        return [pscustomobject]$result
    }

    try {
        $scoreboardDate = $DateValue.Replace('-', '')
        switch ($Sport.Trim().ToLowerInvariant()) {
            'nba' {
                $url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=$scoreboardDate"
                $payload = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 20
                $eventCount = if ($payload -and $payload.events) { [int]$payload.events.Count } else { 0 }
                $result.known = $true
                $result.source = 'espn_nba_scoreboard'
                $result.count = $eventCount
            }
            'wnba' {
                $url = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates=$scoreboardDate"
                $payload = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 20
                $eventCount = if ($payload -and $payload.events) { [int]$payload.events.Count } else { 0 }
                $result.known = $true
                $result.source = 'espn_wnba_scoreboard'
                $result.count = $eventCount
            }
        }
    }
    catch {
        $result.note = $_.Exception.Message
    }

    return [pscustomobject]$result
}

function Get-NhlScheduledGamesCheck {
    param([string]$DateValue)

    $result = [ordered]@{
        known = $false
        count = $null
        source = 'nhle_schedule'
        note = $null
    }

    if ([string]::IsNullOrWhiteSpace($DateValue)) {
        return [pscustomobject]$result
    }

    try {
        $url = "https://api-web.nhle.com/v1/schedule/$DateValue"
        $payload = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 20
        $gameCount = 0
        foreach ($week in @($payload.gameWeek)) {
            if (-not $week) { continue }
            if ([string]$week.date -ne $DateValue) { continue }
            $gameCount += @($week.games).Count
        }
        $result.known = $true
        $result.count = [int]$gameCount
    }
    catch {
        $result.note = $_.Exception.Message
    }

    return [pscustomobject]$result
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

function Convert-ToDoubleOrNull {
    param($Value)

    if ($null -eq $Value) {
        return $null
    }

    $parsed = 0.0
    if ([double]::TryParse([string]$Value, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$parsed)) {
        return $parsed
    }
    return $null
}

function Test-NhlPlaceholderLineupProfile {
    param([string]$LineupsCsvPath)

    if ([string]::IsNullOrWhiteSpace($LineupsCsvPath) -or -not (Test-Path $LineupsCsvPath)) {
        return $false
    }

    $rows = @(Import-Csv -Path $LineupsCsvPath)
    if ($rows.Count -eq 0) {
        return $false
    }

    $skaters = @($rows | Where-Object {
        $positionText = [string]$_.position
        -not $positionText.Trim().ToUpperInvariant().StartsWith('G')
    })
    if ($skaters.Count -eq 0) {
        return $false
    }

    foreach ($row in $skaters) {
        $toiValue = Convert-ToDoubleOrNull $row.proj_toi
        $confidenceValue = Convert-ToDoubleOrNull $row.confidence
        if ($null -eq $toiValue -or $null -eq $confidenceValue) {
            return $false
        }
        if ([Math]::Abs($toiValue - 15.0) -gt 0.000001) {
            return $false
        }
        if ([Math]::Abs($confidenceValue - 0.5) -gt 0.000001) {
            return $false
        }
    }

    return $true
}

function Assert-AdvancedDataReady {
    param(
        [string]$Sport,
        [string]$DateValue,
        [string]$RepoRoot
    )

    if ([string]::IsNullOrWhiteSpace($Sport) -or [string]::IsNullOrWhiteSpace($DateValue) -or [string]::IsNullOrWhiteSpace($RepoRoot)) {
        return
    }

    function Resolve-ExistingRoot {
        param([string[]]$Candidates)

        foreach ($candidate in @($Candidates)) {
            if ([string]::IsNullOrWhiteSpace($candidate)) {
                continue
            }
            if (Test-Path $candidate) {
                return $candidate
            }
        }

        if ($Candidates -and $Candidates.Count -gt 0) {
            return $Candidates[0]
        }
        return $null
    }

    $sportSlug = $Sport.Trim().ToLowerInvariant()
    switch ($sportSlug) {
        'nba' {
            $scheduleCheck = Get-BasketballScheduledGamesCheck -Sport 'nba' -DateValue $DateValue
            if ($scheduleCheck.known -and [int]$scheduleCheck.count -eq 0) {
                Write-Host ("NBA advanced-data gate: no scheduled games for {0} ({1}); skipping artifact assertions" -f $DateValue, $scheduleCheck.source) -ForegroundColor DarkGray
                return
            }
            $processedRoot = Join-Path $RepoRoot 'data\nba_source\data\processed'
            if (-not (Test-Path $processedRoot)) {
                throw "NBA advanced-data gate failed: missing processed root $processedRoot"
            }
            $requiredBoardArtifacts = @(
                (Join-Path $processedRoot ("game_cards_{0}.csv" -f $DateValue)),
                (Join-Path $processedRoot ("recommendations_slate_{0}.json" -f $DateValue)),
                (Join-Path $processedRoot ("cards_props_snapshot_{0}.json" -f $DateValue))
            )
            foreach ($requiredArtifact in $requiredBoardArtifacts) {
                if (-not (Test-Path $requiredArtifact)) {
                    throw "NBA advanced-data gate failed: missing required board artifact $requiredArtifact"
                }
            }
            $smartSimFiles = @(Get-ChildItem -Path $processedRoot -File -Filter ("smart_sim_{0}_*.json" -f $DateValue) -ErrorAction SilentlyContinue)
            if ($smartSimFiles.Count -eq 0) {
                throw "NBA advanced-data gate failed: missing smart_sim artifacts for $DateValue"
            }
            $advancedFiles = @(Get-ChildItem -Path $processedRoot -File -Filter 'team_advanced_stats_*.csv' -ErrorAction SilentlyContinue)
            if ($advancedFiles.Count -eq 0) {
                throw 'NBA advanced-data gate failed: missing mirrored team_advanced_stats artifacts'
            }
            $foundNonBaselinePace = $false
            $foundUsableSmartSimPayload = $false
            foreach ($smartSimFile in $smartSimFiles) {
                try {
                    $payload = Get-Content -Path $smartSimFile.FullName -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
                    $homePace = Convert-ToDoubleOrNull $payload.home_pace
                    $awayPace = Convert-ToDoubleOrNull $payload.away_pace
                    if (($null -ne $homePace -and [Math]::Abs($homePace - 100.0) -gt 0.01) -or ($null -ne $awayPace -and [Math]::Abs($awayPace - 100.0) -gt 0.01)) {
                        $foundNonBaselinePace = $true
                        break
                    }

                    $quarters = @()
                    if ($null -ne $payload.quarters) {
                        $quarters = @($payload.quarters)
                    }
                    $homePlayers = @()
                    $awayPlayers = @()
                    if ($null -ne $payload.players) {
                        if ($null -ne $payload.players.home) {
                            $homePlayers = @($payload.players.home)
                        }
                        if ($null -ne $payload.players.away) {
                            $awayPlayers = @($payload.players.away)
                        }
                    }
                    if ($quarters.Count -gt 0 -or $homePlayers.Count -gt 0 -or $awayPlayers.Count -gt 0) {
                        $foundUsableSmartSimPayload = $true
                    }
                }
                catch {
                }
            }
            if (-not $foundNonBaselinePace -and -not $foundUsableSmartSimPayload) {
                throw "NBA advanced-data gate failed: smart_sim pace remained at baseline for all artifacts on $DateValue"
            }
            return
        }
        'wnba' {
            $scheduleCheck = Get-BasketballScheduledGamesCheck -Sport 'wnba' -DateValue $DateValue
            if ($scheduleCheck.known -and [int]$scheduleCheck.count -eq 0) {
                Write-Host ("WNBA advanced-data gate: no scheduled games for {0} ({1}); skipping artifact assertions" -f $DateValue, $scheduleCheck.source) -ForegroundColor DarkGray
                return
            }
            $processedRoot = Join-Path $RepoRoot 'data\wnba_source\data\processed'
            if (-not (Test-Path $processedRoot)) {
                throw "WNBA advanced-data gate failed: missing processed root $processedRoot"
            }
            $requiredBoardArtifacts = @(
                (Join-Path $processedRoot ("game_cards_{0}.csv" -f $DateValue)),
                (Join-Path $processedRoot ("recommendations_slate_{0}.json" -f $DateValue)),
                (Join-Path $processedRoot ("cards_props_snapshot_{0}.json" -f $DateValue))
            )
            foreach ($requiredArtifact in $requiredBoardArtifacts) {
                if (-not (Test-Path $requiredArtifact)) {
                    throw "WNBA advanced-data gate failed: missing required board artifact $requiredArtifact"
                }
            }
            $smartSimFiles = @(Get-ChildItem -Path $processedRoot -File -Filter ("smart_sim_{0}_*.json" -f $DateValue) -ErrorAction SilentlyContinue)
            if ($smartSimFiles.Count -eq 0) {
                throw "WNBA advanced-data gate failed: missing smart_sim artifacts for $DateValue"
            }
            $advancedFiles = @(Get-ChildItem -Path $processedRoot -File -Filter 'team_advanced_stats_*.csv' -ErrorAction SilentlyContinue)
            if ($advancedFiles.Count -eq 0) {
                throw 'WNBA advanced-data gate failed: missing mirrored team_advanced_stats artifacts'
            }
            $foundNonBaselinePace = $false
            $foundUsableSmartSimPayload = $false
            foreach ($smartSimFile in $smartSimFiles) {
                try {
                    $payload = Get-Content -Path $smartSimFile.FullName -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
                    $homePace = Convert-ToDoubleOrNull $payload.home_pace
                    $awayPace = Convert-ToDoubleOrNull $payload.away_pace
                    if (($null -ne $homePace -and [Math]::Abs($homePace - 79.5) -gt 0.01) -or ($null -ne $awayPace -and [Math]::Abs($awayPace - 79.5) -gt 0.01)) {
                        $foundNonBaselinePace = $true
                        break
                    }

                    $quarters = @()
                    if ($null -ne $payload.quarters) {
                        $quarters = @($payload.quarters)
                    }
                    $homePlayers = @()
                    $awayPlayers = @()
                    if ($null -ne $payload.players) {
                        if ($null -ne $payload.players.home) {
                            $homePlayers = @($payload.players.home)
                        }
                        if ($null -ne $payload.players.away) {
                            $awayPlayers = @($payload.players.away)
                        }
                    }
                    if ($quarters.Count -gt 0 -or $homePlayers.Count -gt 0 -or $awayPlayers.Count -gt 0) {
                        $foundUsableSmartSimPayload = $true
                    }
                }
                catch {
                }
            }
            if (-not $foundNonBaselinePace -and -not $foundUsableSmartSimPayload) {
                throw "WNBA advanced-data gate failed: smart_sim pace remained at baseline for all artifacts on $DateValue"
            }
            return
        }
        'mlb' {
            $dateSlug = $DateValue -replace '-', '_'
            $processedRoots = @(
                (Join-Path $RepoRoot 'data\mlb_source\data\processed'),
                (Join-Path $RepoRoot 'data\mlb_source\source_artifacts\data\processed')
            )
            $dailyTopPropsCandidates = @(
                (Join-Path $RepoRoot ("data\mlb_source\data\daily\top_props\daily_top_props_{0}.json" -f $dateSlug)),
                (Join-Path $RepoRoot ("data\mlb_source\source_artifacts\data\daily\top_props\daily_top_props_{0}.json" -f $dateSlug))
            )
            $liveLensRoots = @(
                (Join-Path $RepoRoot 'data\mlb_source\data\live_lens'),
                (Join-Path $RepoRoot 'data\mlb_source\source_artifacts\data\live_lens')
            )

            $legacyArtifactsReady = $false
            foreach ($candidateProcessedRoot in $processedRoots) {
                $legacyRequiredPaths = @(
                    (Join-Path $candidateProcessedRoot ("props_predictions_{0}.csv" -f $DateValue)),
                    (Join-Path $candidateProcessedRoot ("props_recommendations_{0}.csv" -f $DateValue)),
                    (Join-Path $candidateProcessedRoot ("top_props_{0}.json" -f $DateValue))
                )
                $allPresent = $true
                foreach ($legacyPath in $legacyRequiredPaths) {
                    if (-not (Test-Path $legacyPath)) {
                        $allPresent = $false
                        break
                    }
                }
                if ($allPresent) {
                    $legacyArtifactsReady = $true
                    break
                }
            }

            $modernArtifactsReady = $false
            foreach ($dailyTopPropsPath in $dailyTopPropsCandidates) {
                if (Test-Path $dailyTopPropsPath) {
                    $modernArtifactsReady = $true
                    break
                }
            }

            if (-not $legacyArtifactsReady -and -not $modernArtifactsReady) {
                throw "MLB advanced-data gate failed: missing both legacy processed props artifacts and daily top-props artifact for $DateValue"
            }

            $reportCandidates = @(
                (Join-Path $processedRoots[0] ("live_lens_report_{0}.json" -f $DateValue)),
                (Join-Path $processedRoots[0] ("live_lens_report_{0}.json" -f $dateSlug)),
                (Join-Path $processedRoots[1] ("live_lens_report_{0}.json" -f $DateValue)),
                (Join-Path $processedRoots[1] ("live_lens_report_{0}.json" -f $dateSlug)),
                (Join-Path $liveLensRoots[0] ("live_lens_report_{0}.json" -f $DateValue)),
                (Join-Path $liveLensRoots[0] ("live_lens_report_{0}.json" -f $dateSlug)),
                (Join-Path $liveLensRoots[1] ("live_lens_report_{0}.json" -f $DateValue)),
                (Join-Path $liveLensRoots[1] ("live_lens_report_{0}.json" -f $dateSlug))
            )
            $reportPath = $null
            foreach ($candidate in $reportCandidates) {
                if (Test-Path $candidate) {
                    $reportPath = $candidate
                    break
                }
            }
            if ([string]::IsNullOrWhiteSpace($reportPath)) {
                Write-Host "MLB advanced-data gate warning: missing live_lens_report for $DateValue; continuing because MLB props artifacts are present" -ForegroundColor Yellow
                return
            }

            try {
                $reportPayload = Get-Content -Path $reportPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
                if ($null -ne $reportPayload.error) {
                    throw "MLB advanced-data gate failed: live_lens_report has error payload ($reportPath)"
                }
                $performance = $reportPayload.performance
                if ($null -ne $performance -and $performance.degraded -eq $true) {
                    throw "MLB advanced-data gate failed: live_lens_report is degraded ($reportPath)"
                }
            }
            catch {
                if ($_.Exception.Message -like 'MLB advanced-data gate failed:*') {
                    throw
                }
                throw "MLB advanced-data gate failed: unable to validate live_lens_report payload ($reportPath): $($_.Exception.Message)"
            }
            return
        }
        'nhl' {
            $scheduleCheck = Get-NhlScheduledGamesCheck -DateValue $DateValue
            if ($scheduleCheck.known -and [int]$scheduleCheck.count -eq 0) {
                Write-Host ("NHL advanced-data gate: no scheduled games for {0} ({1}); skipping artifact assertions" -f $DateValue, $scheduleCheck.source) -ForegroundColor DarkGray
                return
            }
            $processedRootCandidates = @(
                (Join-Path $RepoRoot 'data\nhl_source\data\processed'),
                (Join-Path $RepoRoot 'data\nhl_source\source_artifacts\data\processed')
            )
            $processedRoot = $null
            foreach ($candidateRoot in $processedRootCandidates) {
                if (-not (Test-Path $candidateRoot)) {
                    continue
                }

                $candidateRequiredPaths = @(
                    (Join-Path $candidateRoot ("lineups_{0}.csv" -f $DateValue)),
                    (Join-Path $candidateRoot ("lineups_co_toi_{0}.csv" -f $DateValue)),
                    (Join-Path $candidateRoot ("shifts_{0}.csv" -f $DateValue)),
                    (Join-Path $candidateRoot ("props_predictions_{0}.csv" -f $DateValue)),
                    (Join-Path $candidateRoot ("props_recommendations_{0}.csv" -f $DateValue))
                )
                $allCandidateArtifactsPresent = $true
                foreach ($candidateRequiredPath in $candidateRequiredPaths) {
                    if (-not (Test-Path $candidateRequiredPath)) {
                        $allCandidateArtifactsPresent = $false
                        break
                    }
                }
                if ($allCandidateArtifactsPresent) {
                    $processedRoot = $candidateRoot
                    break
                }
            }
            if ([string]::IsNullOrWhiteSpace($processedRoot)) {
                throw ("NHL advanced-data gate failed: missing required artifacts in any processed root: {0}" -f ($processedRootCandidates -join '; '))
            }

            $lineupsPath = Join-Path $processedRoot ("lineups_{0}.csv" -f $DateValue)

            $smartSimFiles = @(Get-ChildItem -Path $processedRoot -File -Filter ("smart_sim_{0}_*.json" -f $DateValue) -ErrorAction SilentlyContinue)
            if ($smartSimFiles.Count -eq 0) {
                throw "NHL advanced-data gate failed: missing smart_sim artifacts for $DateValue"
            }

            if (Test-NhlPlaceholderLineupProfile -LineupsCsvPath $lineupsPath) {
                throw "NHL advanced-data gate failed: placeholder lineup profile detected in $lineupsPath"
            }
            return
        }
        default {
            return
        }
    }
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

    function Add-DateGameBoxscoreCachePaths {
        param(
            [string]$GameCardsRelativePath,
            [string]$BoxscoreRelativeRoot
        )

        if ([string]::IsNullOrWhiteSpace($GameCardsRelativePath) -or [string]::IsNullOrWhiteSpace($BoxscoreRelativeRoot)) {
            return
        }

        $gameCardsFullPath = Join-Path $RepoPath $GameCardsRelativePath
        if (-not (Test-Path $gameCardsFullPath)) {
            return
        }

        try {
            $gameRows = @(Import-Csv -Path $gameCardsFullPath)
        }
        catch {
            return
        }

        foreach ($row in $gameRows) {
            if (-not $row) {
                continue
            }

            $gameId = [string]($row.game_id)
            if ([string]::IsNullOrWhiteSpace($gameId)) {
                $gameId = [string]($row.gameId)
            }
            if ([string]::IsNullOrWhiteSpace($gameId)) {
                continue
            }

            $normalizedGameId = $gameId.Trim()
            if ([string]::IsNullOrWhiteSpace($normalizedGameId)) {
                continue
            }

            Add-PathIfPresent -RelativePath ($BoxscoreRelativeRoot.TrimEnd('/', '\') + "/boxscore_${normalizedGameId}.csv")
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
            "data/mlb_source/data/live_lens/recaps/live_lens_daily_recap_${dateSlug}.json",
            "data/mlb_source/data/live_lens/render_sync/live_lens_reports_${dateSlug}.json",
            "data/mlb_source/data/live_lens/prop_registry/live_prop_registry_${dateSlug}.json",
            "data/mlb_source/data/live_lens/prop_registry/live_prop_registry_${dateSlug}.jsonl",
            "data/mlb_source/data/live_lens/prop_registry/live_prop_observations_${dateSlug}.jsonl",
            "data/mlb_source/data/tuning/live_prop_ranking/default.json",
            "data/mlb_source/sim_engine/live_prop_ranking.py"
        )) {
            Add-PathIfPresent -RelativePath $relativePath
        }

        Add-PathsByPattern -RelativePattern "data/mlb_source/data/daily/sims/${DateValue}/sim_*.json"
        Add-PathsByPattern -RelativePattern "data/mlb_source/data/daily/season_frontend/season_manifest_*_${dateSlug}.json"
        Add-PathsByPattern -RelativePattern "data/mlb_source/data/daily/season_frontend/season_day_*_${dateSlug}_*.json"
        Add-PathsByPattern -RelativePattern "data/mlb_source/data/daily/season_frontend/season_betting_day_*_${dateSlug}_*.json"
        Add-PathsByPattern -RelativePattern "data/mlb_source/data/daily/season_frontend/season_official_betting_day_*_${dateSlug}_*.json"
        Add-PathsByPattern -RelativePattern "data/mlb_source/data/eval/seasons/*/season_eval_manifest.json"
        Add-PathsByPattern -RelativePattern "data/mlb_source/data/eval/seasons/*/season_betting_cards_retuned_manifest.json"
        Add-PathsByPattern -RelativePattern "data/mlb_source/data/eval/seasons/*/season_betting_cards_retuned_hrr_manifest.json"
        Add-PathsByPattern -RelativePattern "data/mlb_source/data/eval/seasons/*/betting_day_payloads*/season_betting_day_*_${dateSlug}*.json"
        Add-PathsByPattern -RelativePattern "data/mlb_source/data/eval/seasons/*/betting_day_recaps*/season_betting_day_*_${dateSlug}*.json"
    }

    if (-not $SkipNBA) {
        foreach ($relativePath in @(
            "data/nba_source/data/processed/game_cards_${DateValue}.csv",
            "data/nba_source/data/processed/game_odds_${DateValue}.csv",
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
        Add-PathsByPattern -RelativePattern "data/nba_source/data/processed/team_advanced_stats_*.csv"
        Add-PathsByPattern -RelativePattern "data/nba_source/data/processed/season_betting_card_manifest_*_retuned_${DateValue}.json"
        Add-PathsByPattern -RelativePattern "data/nba_source/data/processed/season_betting_card_manifest_*_retuned.json"
        Add-PathsByPattern -RelativePattern "data/nba_source/data/processed/season_betting_card_day_*_retuned_${DateValue}.json"
        Add-PathsByPattern -RelativePattern "data/nba_source/data/processed/season_betting_card_day_*_retuned_${DateValue}_insights.json"
        Add-DateGameBoxscoreCachePaths -GameCardsRelativePath "data/nba_source/data/processed/game_cards_${DateValue}.csv" -BoxscoreRelativeRoot 'data/nba_source/data/processed/boxscores'
    }

    if (-not $SkipWNBA) {
        foreach ($relativePath in @(
            "data/wnba_source/data/processed/game_cards_${DateValue}.csv",
            "data/wnba_source/data/processed/game_odds_${DateValue}.csv",
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
        Add-PathsByPattern -RelativePattern "data/wnba_source/data/processed/team_advanced_stats_*.csv"
        Add-DateGameBoxscoreCachePaths -GameCardsRelativePath "data/wnba_source/data/processed/game_cards_${DateValue}.csv" -BoxscoreRelativeRoot 'data/wnba_source/data/processed/boxscores'
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
            "data/nhl_source/data/processed/props_projections_all_${DateValue}.csv",
            "data/nhl_source/data/processed/props_boxscores_sim_${DateValue}.csv",
            "data/nhl_source/data/processed/props_boxscores_sim_hist_${DateValue}.csv",
            "data/nhl_source/data/processed/props_boxscores_sim_samples_${DateValue}.csv",
            "data/nhl_source/data/processed/props_recommendations_${DateValue}.csv",
            "data/nhl_source/data/processed/roster_snapshot_${DateValue}.csv",
            "data/nhl_source/data/processed/injuries_${DateValue}.csv",
            "data/nhl_source/data/processed/lineups_${DateValue}.csv",
            "data/nhl_source/data/processed/lineups_co_toi_${DateValue}.csv",
            "data/nhl_source/data/processed/shifts_${DateValue}.csv",
            "data/nhl_source/data/processed/co_toi_shifts_${DateValue}.csv",
            "data/nhl_source/data/processed/starting_goalies_${DateValue}.csv",
            "data/nhl_source/data/processed/smart_sim_${DateValue}_bundle.json",
            "data/nhl_source/data/processed/live_lens_projections_${DateValue}.jsonl",
            "data/nhl_source/data/processed/live_lens_signals_${DateValue}.jsonl",
            "data/nhl_source/data/processed/live_lens_tuning_override.json",
            "data/nhl_source/data/live_lens/live_lens_projections_${DateValue}.jsonl",
            "data/nhl_source/data/live_lens/live_lens_signals_${DateValue}.jsonl",
            "data/nhl_source/data/live_lens/live_lens_tuning_override.json",
            "data/nhl_source/data/odds/games/date=${DateValue}/scoreboard.csv",
            "data/nhl_source/data/odds/team/date=${DateValue}/oddsapi.csv",
            "data/nhl_source/data/odds/team/date=${DateValue}/oddsapi.parquet",
            "data/nhl_source/data/props/player_props_lines/date=${DateValue}/oddsapi.csv",
            "data/nhl_source/data/props/player_props_lines/date=${DateValue}/oddsapi.parquet"
        )) {
            Add-PathIfPresent -RelativePath $relativePath
        }

        foreach ($relativePath in @(
            "data/nhl_source/source_artifacts/data/processed/predictions_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/predictions_sim_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/recommendations_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/recommendations_sim_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/reconciliations_log.csv",
            "data/nhl_source/source_artifacts/data/processed/props_reconciliations_log.csv",
            "data/nhl_source/source_artifacts/data/processed/recon_games_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/recon_props_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/props_projections_all_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/props_boxscores_sim_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/props_boxscores_sim_hist_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/props_boxscores_sim_samples_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/props_recommendations_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/roster_snapshot_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/injuries_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/lineups_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/lineups_co_toi_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/shifts_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/co_toi_shifts_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/starting_goalies_${DateValue}.csv",
            "data/nhl_source/source_artifacts/data/processed/smart_sim_${DateValue}_bundle.json",
            "data/nhl_source/source_artifacts/data/processed/live_lens_projections_${DateValue}.jsonl",
            "data/nhl_source/source_artifacts/data/processed/live_lens_signals_${DateValue}.jsonl",
            "data/nhl_source/source_artifacts/data/processed/live_lens_tuning_override.json",
            "data/nhl_source/source_artifacts/data/live_lens/live_lens_projections_${DateValue}.jsonl",
            "data/nhl_source/source_artifacts/data/live_lens/live_lens_signals_${DateValue}.jsonl",
            "data/nhl_source/source_artifacts/data/live_lens/live_lens_tuning_override.json",
            "data/nhl_source/source_artifacts/data/odds/games/date=${DateValue}/scoreboard.csv",
            "data/nhl_source/source_artifacts/data/odds/team/date=${DateValue}/oddsapi.csv",
            "data/nhl_source/source_artifacts/data/odds/team/date=${DateValue}/oddsapi.parquet",
            "data/nhl_source/source_artifacts/data/props/player_props_lines/date=${DateValue}/oddsapi.csv",
            "data/nhl_source/source_artifacts/data/props/player_props_lines/date=${DateValue}/oddsapi.parquet"
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

        # Only attempt commit when there are staged changes.
        & git diff --cached --quiet --exit-code
        $stagedDiffExitCode = $LASTEXITCODE
        if ($stagedDiffExitCode -eq 0) {
            $result.status = 'no_changes'
            return [pscustomobject]$result
        }
        if ($stagedDiffExitCode -ne 1) {
            throw "git diff --cached --quiet failed for $RepoPath with exit code $stagedDiffExitCode"
        }

        $commitOutput = @(& git commit -m $CommitMessage 2>&1)
        if ($LASTEXITCODE -ne 0) {
            $commitText = ($commitOutput | Out-String)
            if ($commitText -match '(?i)nothing to commit|no changes added to commit') {
                $result.status = 'no_changes'
                return [pscustomobject]$result
            }
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
$resolveForcedPublishArtifactPaths = {
    Get-ForcedPublishArtifactPaths -RepoPath $repoRoot -DateValue $Date -SkipMLB ([bool]$SkipMLB) -SkipNBA ([bool]$SkipNBA) -SkipNHL ([bool]$SkipNHL) -SkipWNBA ([bool]$SkipWNBA) -SkipNCAAB ([bool]$SkipNCAAB)
}
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
        APP_TZ = 'America/Chicago'
        APP_TZ_OFFSET_HOURS = '-6'
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
        APP_TZ = 'America/Chicago'
        APP_TZ_OFFSET_HOURS = '-6'
        SYNDICATE_WNBA_SOURCE_APP_FALLBACK = '1'
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
            $result = Invoke-GitPublish -Name $repo.Name -RepoPath $repo.RepoPath -CommitMessage "$CommitMessagePrefix $Date (pre-source publish)" -RemoteName $GitRemote -ForceIncludePaths (& $resolveForcedPublishArtifactPaths)
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
        for ($stepIndex = 0; $stepIndex -lt $sourceSteps.Count; $stepIndex++) {
            $step = $sourceSteps[$stepIndex]
            $sportKey = [string]$step.Sport
            $startedAt = (Get-Date).ToString('o')
            $isMlbVendoredStep = ($step.Sport -eq 'mlb' -and $step.Workflow -eq 'vendored_daily_update')
            $mlbDataRootForStep = $null
            if ($isMlbVendoredStep -and $step.EnvironmentOverrides -and $step.EnvironmentOverrides.ContainsKey('MLB_BETTING_DATA_ROOT')) {
                $mlbDataRootForStep = [string]$step.EnvironmentOverrides.MLB_BETTING_DATA_ROOT
            }
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

            if (-not $DryRun -and $isMlbVendoredStep) {
                $preRemovedLocks = Clear-StaleMlbUiDailyLocks -MlbDataRoot $mlbDataRootForStep -DateValue $Date -SeasonValue $season
                if ($preRemovedLocks -gt 0) {
                    Write-Host ("    cleaned stale MLB ui-daily locks before run: {0}" -f $preRemovedLocks) -ForegroundColor Yellow
                }
                Wait-ForMlbUiDailyLockRelease -MlbDataRoot $mlbDataRootForStep -DateValue $Date -SeasonValue $season
            }

            $stepSucceeded = $false
            try {
                Invoke-Step -Name $step.Name -Command $step.Command -WorkingDirectory $step.WorkingDirectory -EnvironmentOverrides $step.EnvironmentOverrides
                $stepSucceeded = $true
            }
            catch {
                if (-not $DryRun -and $isMlbVendoredStep) {
                    $retryRemovedLocks = Clear-StaleMlbUiDailyLocks -MlbDataRoot $mlbDataRootForStep -DateValue $Date -SeasonValue $season
                    if ($retryRemovedLocks -gt 0) {
                        Write-Host '    retrying MLB vendored daily update after stale-lock cleanup' -ForegroundColor Yellow
                        Invoke-Step -Name $step.Name -Command $step.Command -WorkingDirectory $step.WorkingDirectory -EnvironmentOverrides $step.EnvironmentOverrides
                        $stepSucceeded = $true
                    }
                }

                if (-not $stepSucceeded) {
                    $sportRun.status = 'error'
                    $sportRun.error = $_.Exception.Message
                    $sportRun.completedAt = (Get-Date).ToString('o')
                    $runManifest.sportRuns += @([pscustomobject]$sportRun)
                    throw
                }
            }
            $sportRun.status = if ($DryRun) { 'dry_run' } else { 'ok' }
            $sportRun.completedAt = (Get-Date).ToString('o')
            $runManifest.sportRuns += @([pscustomobject]$sportRun)

            $hasLaterStepForSport = $false
            for ($nextStepIndex = $stepIndex + 1; $nextStepIndex -lt $sourceSteps.Count; $nextStepIndex++) {
                $nextSport = [string]$sourceSteps[$nextStepIndex].Sport
                if (-not [string]::IsNullOrWhiteSpace($nextSport) -and $nextSport.Equals([string]$step.Sport, [System.StringComparison]::OrdinalIgnoreCase)) {
                    $hasLaterStepForSport = $true
                    break
                }
            }

            if (-not $DryRun -and -not $hasLaterStepForSport) {
                Assert-AdvancedDataReady -Sport $step.Sport -DateValue $Date -RepoRoot $repoRoot -RunDir $runDir
            }

            if (-not $SkipGitPush) {
                foreach ($repo in $publishRepos) {
                    $result = Invoke-GitPublish -Name $repo.Name -RepoPath $repo.RepoPath -CommitMessage "$CommitMessagePrefix $Date [$($step.Name)]" -RemoteName $GitRemote -ForceIncludePaths (& $resolveForcedPublishArtifactPaths)
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
            $result = Invoke-GitPublish -Name $repo.Name -RepoPath $repo.RepoPath -CommitMessage $repo.CommitMessage -RemoteName $GitRemote -ForceIncludePaths (& $resolveForcedPublishArtifactPaths)
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