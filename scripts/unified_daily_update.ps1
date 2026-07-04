<#
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md
Role:
- Main orchestration controller for planning, state updates, simulation, artifact generation, and publish.

Constraints:
- State-driven execution
- Avoid redundant computation
#>

param(
    [string]$Date,
    [string]$BaseUrl,
    [int]$EventSimForceWindowMinutes = 30,
    [string[]]$ActiveSports,
    [switch]$SkipGitPush,
    [switch]$ForceRebuildToday,
    [switch]$DryRun
)


if ($env:PYTHON_PATH) {
    $python = $env:PYTHON_PATH.Split("`n")[0].Trim()
} else {
    $python = "python"
}

Write-Host "Unified script using Python: $python"

function Get-ReasonableWorkerCount {
    param([int]$Requested)

    $safeCpu = [Environment]::ProcessorCount
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

$runManifestPath = Join-Path $runDir 'unified_daily_update_run.json'
$latestManifestPath = Join-Path $latestDir 'unified_daily_update_latest.json'
$runCheckpointPath = Join-Path $runDir 'unified_daily_update_checkpoint.json'
$latestCheckpointPath = Join-Path $latestDir 'unified_daily_update_latest_checkpoint.json'
$runStatePath = Join-Path $runDir 'unified_daily_update_run_state.json'
$latestRunStatePath = Join-Path $latestDir 'unified_daily_update_latest_run_state.json'
$runTracePath = Join-Path $runDir 'unified_daily_update_run_trace.json'
$latestRunTracePath = Join-Path $latestDir 'unified_daily_update_latest_run_trace.json'
$runSimulationContractPath = Join-Path $runDir 'unified_daily_update_simulation_contract.json'
$latestSimulationContractPath = Join-Path $latestDir 'unified_daily_update_latest_simulation_contract.json'

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

$normalizedActiveSports = @(
    $ActiveSports |
        ForEach-Object { [string]$_ } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
)
$activeSportsLookup = @{}
foreach ($sport in $normalizedActiveSports) {
    $activeSportsLookup[$sport.ToUpperInvariant()] = $true
}
$useActiveSportsGate = $normalizedActiveSports.Count -gt 0

if ($useActiveSportsGate) {
    $SkipMLB = -not $activeSportsLookup.ContainsKey('MLB')
    $SkipNBA = -not $activeSportsLookup.ContainsKey('NBA')
    $SkipNHL = -not $activeSportsLookup.ContainsKey('NHL')
    $SkipWNBA = -not $activeSportsLookup.ContainsKey('WNBA')
    $SkipNFL = -not $activeSportsLookup.ContainsKey('NFL')
    $SkipNCAAF = -not $activeSportsLookup.ContainsKey('NCAAF')
    $SkipNCAAB = -not $activeSportsLookup.ContainsKey('NCAAB')
}

function Test-SportEnabled {
    param([string]$Sport)

    if ([string]::IsNullOrWhiteSpace($Sport)) {
        return $false
    }

    $sportKey = $Sport.ToUpperInvariant()
    if ($useActiveSportsGate) {
        return $activeSportsLookup.ContainsKey($sportKey)
    }

    switch ($sportKey) {
        'MLB' { return -not [bool]$SkipMLB }
        'NBA' { return -not [bool]$SkipNBA }
        'NHL' { return -not [bool]$SkipNHL }
        'WNBA' { return -not [bool]$SkipWNBA }
        'NFL' { return -not [bool]$SkipNFL }
        'NCAAF' { return -not [bool]$SkipNCAAF }
        'NCAAB' { return -not [bool]$SkipNCAAB }
        default { return $false }
    }
}

$eventSimPolicyConfig = [ordered]@{
    sport = [ordered]@{
        mlb = [ordered]@{
            policyId = 'sport:mlb:default'
            forceWithinMinutes = 20
            minimumSampleSize = 3
            explorationRate = 0.05
            policyCandidates = @(
                [ordered]@{ policyId = 'sport:mlb:default'; forceWithinMinutes = 20 }
                [ordered]@{ policyId = 'sport:mlb:balanced'; forceWithinMinutes = 30 }
            )
        }
        nba = [ordered]@{
            policyId = 'sport:nba:default'
            forceWithinMinutes = 45
            minimumSampleSize = 3
            explorationRate = 0.05
            policyCandidates = @(
                [ordered]@{ policyId = 'sport:nba:default'; forceWithinMinutes = 45 }
                [ordered]@{ policyId = 'sport:nba:late'; forceWithinMinutes = 60 }
            )
        }
        wnba = [ordered]@{ policyId = 'sport:wnba:default'; forceWithinMinutes = 40; minimumSampleSize = 3; explorationRate = 0.05; policyCandidates = @([ordered]@{ policyId = 'sport:wnba:default'; forceWithinMinutes = 40 }) }
        nhl = [ordered]@{ policyId = 'sport:nhl:default'; forceWithinMinutes = 25; minimumSampleSize = 3; explorationRate = 0.05; policyCandidates = @([ordered]@{ policyId = 'sport:nhl:default'; forceWithinMinutes = 25 }) }
    }
}

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

        # ✅ Force python commands to use the correct interpreter
        if ($resolvedCommand -eq "python") {
            $resolvedCommand = $python
        }
        else {
            $commandInfo = Get-Command -Name $Command[0] -ErrorAction SilentlyContinue
            if ($commandInfo -and -not [string]::IsNullOrWhiteSpace($commandInfo.Source)) {
                $resolvedCommand = $commandInfo.Source
            }
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
        if ($exitCode -ne 0) {
            $stepHasArtifacts = $false
            if ($Name -like "*WNBA*") {
                $stepHasArtifacts = Test-WnbaDateArtifactsPresent -RepoRootPath $repoRoot -DateValue $Date
            }
            else {
                $artifactRoot = Join-Path $repoRoot "data"
                if ($Name -like "*MLB*") {
                    $stepHasArtifacts = Test-Path (Join-Path $artifactRoot "mlb_source")
                }
                elseif ($Name -like "*NBA*") {
                    $stepHasArtifacts = Test-Path (Join-Path $artifactRoot "nba_source")
                }
                elseif ($Name -like "*NHL*") {
                    $stepHasArtifacts = Test-Path (Join-Path $artifactRoot "nhl_source")
                }
                elseif ($Name -like "*NFL*") {
                    $stepHasArtifacts = Test-Path (Join-Path $artifactRoot "nfl_source")
                }
            }

            if ($stepHasArtifacts) {
                Write-Host "$Name returned exit code $exitCode but artifacts exist → treating as success" -ForegroundColor Yellow
                return
            }

            $exitCodeText = [string]$exitCode
            Write-Host "$Name failed with exit code $exitCodeText (no artifacts found)" -ForegroundColor Red
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

function Test-WnbaDateArtifactsPresent {
    param(
        [string]$RepoRootPath,
        [string]$DateValue
    )

    if ([string]::IsNullOrWhiteSpace($RepoRootPath) -or [string]::IsNullOrWhiteSpace($DateValue)) {
        return $false
    }

    $candidateRoots = @(
        (Join-Path $RepoRootPath 'data\wnba_source\data\processed'),
        (Join-Path $RepoRootPath 'data\wnba_source\source_artifacts\data\processed')
    )
    $requiredFiles = @(
        "game_cards_$DateValue.csv",
        "recommendations_slate_$DateValue.json",
        "cards_sim_detail_$DateValue.json",
        "cards_props_snapshot_$DateValue.json"
    )

    foreach ($root in $candidateRoots) {
        if ([string]::IsNullOrWhiteSpace($root) -or -not (Test-Path $root)) {
            continue
        }

        $allPresent = $true
        foreach ($fileName in $requiredFiles) {
            if (-not (Test-Path (Join-Path $root $fileName))) {
                $allPresent = $false
                break
            }
        }

        if ($allPresent) {
            return $true
        }
    }

    return $false
}

function Test-ProcessIdRunning {
    param([int]$ProcessId)

    if ($ProcessId -le 0) {
        return $false
    }

    return [bool](Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Write-RunManifest {
    param([psobject]$Manifest)

    Sync-RunStateArtifacts -Manifest $Manifest
    $Manifest | ConvertTo-Json -Depth 8 | Set-Content -Path $runManifestPath -Encoding utf8
    $Manifest | ConvertTo-Json -Depth 8 | Set-Content -Path $latestManifestPath -Encoding utf8
}

function Write-RunCheckpoint {
    param([psobject]$Manifest)

    if ($null -eq $Manifest) {
        return
    }

    $checkpoint = [ordered]@{
        scope = 'daily_update'
        date = $Manifest.date
        runMode = $Manifest.runMode
        overallStatus = $Manifest.overallStatus
        generatedAt = $Manifest.generatedAt
        updatedAt = (Get-Date).ToString('o')
        runDir = $Manifest.runDir
        latestDir = $Manifest.latestDir
        lastUpdatedAt = $Manifest.lastUpdatedAt
        currentStage = $Manifest.runState.currentStage
        completedStages = @($Manifest.runState.completedStages)
        failedStage = $Manifest.runState.failedStage
        stageDecisions = @($Manifest.stageDecisions)
        provenance = $Manifest.runProvenance
        trace = $Manifest.runTrace
        replayContext = $Manifest.replayContext
        runPlan = [ordered]@{
            simExecution = $Manifest.runPlan.simExecution
            sourceUpdates = $Manifest.runPlan.sourceUpdates
            refreshGate = $Manifest.runPlan.refreshGate
            artifactGeneration = $Manifest.runPlan.artifactGeneration
            manifestGeneration = $Manifest.runPlan.manifestGeneration
            publish = $Manifest.runPlan.publish
            refreshOdds = $Manifest.runPlan.refreshOdds
            oddsPhase = $Manifest.runPlan.oddsPhase
            oddsSports = $Manifest.runPlan.oddsSports
            oddsRegions = $Manifest.runPlan.oddsRegions
        }
    }

    $checkpoint | ConvertTo-Json -Depth 8 | Set-Content -Path $runCheckpointPath -Encoding utf8
    $checkpoint | ConvertTo-Json -Depth 8 | Set-Content -Path $latestCheckpointPath -Encoding utf8
}

function Write-RunStateArtifact {
    param([psobject]$Manifest)

    if ($null -eq $Manifest -or $null -eq $Manifest.runState) {
        return
    }

    $runStateArtifact = [ordered]@{
        scope = 'daily_update'
        date = $Manifest.date
        runMode = $Manifest.runMode
        overallStatus = $Manifest.overallStatus
        generatedAt = $Manifest.generatedAt
        updatedAt = (Get-Date).ToString('o')
        runManifestPath = $runManifestPath
        latestManifestPath = $latestManifestPath
        runCheckpointPath = $runCheckpointPath
        latestCheckpointPath = $latestCheckpointPath
        currentStage = $Manifest.runState.currentStage
        completedStages = @($Manifest.runState.completedStages)
        failedStage = $Manifest.runState.failedStage
        lastUpdatedAt = $Manifest.runState.lastUpdatedAt
        replayContext = $Manifest.replayContext
        stageDecisions = @($Manifest.stageDecisions)
        runTrace = $Manifest.runTrace
        simulationContractPath = $Manifest.simulationContractPath
        simulationContractRunPath = $Manifest.simulationContractRunPath
        simulationContractSportCount = $Manifest.simulationContractSportCount
        simulationContractAdvancedBySport = $Manifest.simulationContractAdvancedBySport
    }

    $runStateArtifact | ConvertTo-Json -Depth 8 | Set-Content -Path $runStatePath -Encoding utf8
    $runStateArtifact | ConvertTo-Json -Depth 8 | Set-Content -Path $latestRunStatePath -Encoding utf8
}

function Write-RunTraceArtifact {
    param([psobject]$Manifest)

    if ($null -eq $Manifest) {
        return
    }

    $runTraceArtifact = [ordered]@{
        scope = 'daily_update'
        date = $Manifest.date
        runMode = $Manifest.runMode
        overallStatus = $Manifest.overallStatus
        generatedAt = $Manifest.generatedAt
        updatedAt = (Get-Date).ToString('o')
        runManifestPath = $runManifestPath
        latestManifestPath = $latestManifestPath
        runCheckpointPath = $runCheckpointPath
        latestCheckpointPath = $latestCheckpointPath
        runStatePath = $runStatePath
        latestRunStatePath = $latestRunStatePath
        trace = $Manifest.runTrace
        simulationContractPath = $Manifest.simulationContractPath
        simulationContractRunPath = $Manifest.simulationContractRunPath
        simulationContractSportCount = $Manifest.simulationContractSportCount
        simulationContractAdvancedBySport = $Manifest.simulationContractAdvancedBySport
    }

    $runTraceArtifact | ConvertTo-Json -Depth 8 | Set-Content -Path $runTracePath -Encoding utf8
    $runTraceArtifact | ConvertTo-Json -Depth 8 | Set-Content -Path $latestRunTracePath -Encoding utf8
}

function Write-SimulationContractArtifact {
    param(
        [psobject]$Manifest,
        [string[]]$ActiveSports
    )

    if ($null -eq $Manifest -or -not $ActiveSports) {
        return
    }

    $helperScript = Join-Path $PSScriptRoot 'build_daily_update_simulation_contract.py'
    if (-not (Test-Path -LiteralPath $helperScript)) {
        throw "Simulation contract helper not found: $helperScript"
    }

    $activeSportArg = @($ActiveSports | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join ','
    & $python $helperScript --date $Manifest.date --sports $activeSportArg --run-output $runSimulationContractPath --latest-output $latestSimulationContractPath

    if ($LASTEXITCODE -ne 0) {
        throw "Daily-update simulation contract generation failed with exit code $LASTEXITCODE"
    }

    $simulationContract = Get-Content -LiteralPath $latestSimulationContractPath -Raw | ConvertFrom-Json
    $Manifest | Add-Member -NotePropertyName simulationContractPath -NotePropertyValue $latestSimulationContractPath -Force
    $Manifest | Add-Member -NotePropertyName simulationContractRunPath -NotePropertyValue $runSimulationContractPath -Force
    $Manifest | Add-Member -NotePropertyName simulationContractSportCount -NotePropertyValue @($simulationContract.sports).Count -Force
    $Manifest | Add-Member -NotePropertyName simulationContractAdvancedBySport -NotePropertyValue $simulationContract.advanced_by_sport -Force
}

function Get-RunTraceSnapshot {
    param([psobject]$Manifest)

    if ($null -eq $Manifest) {
        return $null
    }

    $eventSimExecutionRecords = @($Manifest.eventSimExecution)
    $artifactUpdateRecords = @($Manifest.artifactUpdates)
    $inputFingerprints = @(
        $eventSimExecutionRecords |
            ForEach-Object { [string]$_.inputFingerprint } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -Unique
    )
    $artifactPaths = @(
        $artifactUpdateRecords |
            ForEach-Object { [string]$_.artifactPath } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -Unique
    )

    return [ordered]@{
        eventSimExecutionCount = $eventSimExecutionRecords.Count
        artifactUpdateCount = $artifactUpdateRecords.Count
        inputFingerprintCount = $inputFingerprints.Count
        artifactPathCount = $artifactPaths.Count
        inputFingerprints = $inputFingerprints
        artifactPaths = $artifactPaths
        simExecutionDecision = $Manifest.runProvenance.simExecutionDecision
    }
}

function Sync-RunStateArtifacts {
    param([psobject]$Manifest)

    if ($null -eq $Manifest) {
        return
    }

    $updatedAt = (Get-Date).ToString('o')
    $Manifest.lastUpdatedAt = $updatedAt

    if ($Manifest.runState) {
        $Manifest.runState.lastUpdatedAt = $updatedAt
    }

    if ($Manifest.statusArtifact -and $Manifest.statusArtifact.state) {
        $Manifest.statusArtifact.state.runMode = $Manifest.runMode
        $Manifest.statusArtifact.state.overallStatus = $Manifest.overallStatus
        $Manifest.statusArtifact.state.currentStage = $Manifest.runState.currentStage
        $Manifest.statusArtifact.state.completedStages = @($Manifest.runState.completedStages)
        $Manifest.statusArtifact.state.failedStage = $Manifest.runState.failedStage
        $Manifest.statusArtifact.state.lastUpdatedAt = $updatedAt
        $Manifest.statusArtifact.state.policyPerformance = @($Manifest.policyPerformance)
        $Manifest.statusArtifact.state.replayContext = $Manifest.replayContext
    }

    $Manifest.runTrace = Get-RunTraceSnapshot -Manifest $Manifest

    Write-RunStateArtifact -Manifest $Manifest
    Write-RunTraceArtifact -Manifest $Manifest
    Write-RunCheckpoint -Manifest $Manifest
}

function Update-RunStateStage {
    param(
        [psobject]$Manifest,
        [string]$Stage,
        [string]$Status = 'started'
    )

    if ($null -eq $Manifest -or $null -eq $Manifest.runState -or [string]::IsNullOrWhiteSpace($Stage)) {
        return
    }

    $runState = $Manifest.runState
    $runState.currentStage = $Stage

    if ($Status -eq 'completed') {
        $completedStages = @($runState.completedStages)
        if (-not ($completedStages -contains $Stage)) {
            $runState.completedStages += @($Stage)
        }
        $runState.currentStage = 'queued'
    }
    elseif ($Status -eq 'failed') {
        $runState.failedStage = $Stage
    }

    Sync-RunStateArtifacts -Manifest $Manifest
}

function Set-RunTerminalState {
    param(
        [psobject]$Manifest,
        [string]$Stage = 'completed'
    )

    if ($null -eq $Manifest -or $null -eq $Manifest.runState) {
        return
    }

    $Manifest.runState.currentStage = $Stage
    Sync-RunStateArtifacts -Manifest $Manifest
}

function Set-RunFailureState {
    param(
        [psobject]$Manifest,
        [string]$Stage,
        [string]$Message
    )

    if ($null -eq $Manifest) {
        return
    }

    $Manifest.overallStatus = 'error'
    $Manifest.error = $Message
    if ($Manifest.runState) {
        $Manifest.runState.failedStage = $Stage
        $Manifest.runState.currentStage = if ([string]::IsNullOrWhiteSpace($Stage)) { 'failed' } else { $Stage }
    }

    Sync-RunStateArtifacts -Manifest $Manifest
}

function Set-RunReplayContext {
    param(
        [psobject]$Manifest,
        [psobject]$ReplayContext
    )

    if ($null -eq $Manifest -or $null -eq $Manifest.runState -or $null -eq $ReplayContext) {
        return
    }

    if ([bool]$ReplayContext.forceRebuildToday) {
        return
    }

    if (-not [bool]$ReplayContext.resumeEligible) {
        return
    }

    $currentStage = [string]$ReplayContext.latestCheckpointStage
    if ([string]::IsNullOrWhiteSpace($currentStage)) {
        return
    }

    $Manifest.runState.currentStage = $currentStage
    $Manifest.runState.completedStages = @($ReplayContext.latestCheckpointCompletedStages)
    $Manifest.runState.failedStage = [string]$ReplayContext.latestCheckpointFailedStage
    $Manifest.overallStatus = 'resumed'

    foreach ($stageDecision in @($Manifest.stageDecisions)) {
        if ([string]::IsNullOrWhiteSpace([string]$stageDecision.stage)) {
            continue
        }

        if (@($Manifest.runState.completedStages) -contains [string]$stageDecision.stage) {
            $stageDecision.decision = 'completed'
            $stageDecision.status = if ($DryRun) { 'dry_run' } else { 'completed' }
        }
        elseif ([string]$stageDecision.stage -eq [string]$Manifest.runState.currentStage) {
            $stageDecision.decision = 'resumed'
            $stageDecision.status = if ($DryRun) { 'dry_run' } else { 'resumed' }
        }
    }

    Sync-RunStateArtifacts -Manifest $Manifest
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

function Get-RunPlanDecisionValue {
    param(
        [object]$Plan,
        [string]$Key,
        [bool]$Fallback
    )

    if ($null -eq $Plan -or [string]::IsNullOrWhiteSpace($Key)) {
        return $Fallback
    }

    if ($Plan -is [System.Collections.IDictionary]) {
        if ($Plan.Contains($Key)) {
            $plannedValue = $Plan[$Key]
            if ($null -ne $plannedValue) {
                return [bool]$plannedValue
            }
        }

        return $Fallback
    }

    $property = $Plan.PSObject.Properties[$Key]
    if ($null -ne $property -and $null -ne $property.Value) {
        return [bool]$property.Value
    }

    return $Fallback
}

function Get-OddsHistoryPathForSport {
    param(
        [string]$RepoRoot,
        [string]$Sport
    )

    if ([string]::IsNullOrWhiteSpace($RepoRoot) -or [string]::IsNullOrWhiteSpace($Sport)) {
        return $null
    }

    switch ($Sport.ToLowerInvariant()) {
        'mlb' { return Join-Path $RepoRoot 'data\mlb_source\tracking\odds_history.json' }
        'nba' { return Join-Path $RepoRoot 'data\nba_source\tracking\odds_history.json' }
        'wnba' { return Join-Path $RepoRoot 'data\wnba_source\tracking\odds_history.json' }
        'nhl' { return Join-Path $RepoRoot 'data\nhl_source\tracking\odds_history.json' }
        'nfl' { return Join-Path $RepoRoot 'data\nfl_source\tracking\odds_history.json' }
        'ncaaf' { return Join-Path $RepoRoot 'data\ncaaf_source\tracking\odds_history.json' }
        'ncaab' { return Join-Path $RepoRoot 'data\ncaab_source\tracking\odds_history.json' }
        default { return $null }
    }
}

function Get-OddsHistoryTriggerDecision {
    param(
        [string]$RepoRoot,
        [string]$DateValue,
        [string]$Sport,
        [string]$Workflow,
        [double]$DeltaThreshold = 0.5
    )

    $scheduleCheck = $null
    if ($Sport -eq 'nba' -or $Sport -eq 'wnba') {
        $scheduleCheck = Get-BasketballScheduledGamesCheck -Sport $Sport -DateValue $DateValue
    }
    elseif ($Sport -eq 'nhl') {
        $scheduleCheck = Get-NhlScheduledGamesCheck -DateValue $DateValue
    }

    $historyPath = Get-OddsHistoryPathForSport -RepoRoot $RepoRoot -Sport $Sport
    if ([string]::IsNullOrWhiteSpace($historyPath) -or -not (Test-Path -LiteralPath $historyPath)) {
        return $null
    }

    try {
        $payload = Get-Content -Path $historyPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        return $null
    }

    $markets = @()
    if ($null -ne $payload.markets) {
        $markets = @($payload.markets.PSObject.Properties)
    }

    if ($markets.Count -eq 0) {
        return [ordered]@{
            sport = $Sport
            workflow = $Workflow
            date = $DateValue
            oddsHistoryPath = $historyPath
            hasLineMovement = $false
            maxDeltaDetected = $null
            lastOddsUpdateTimestamp = $null
            runSimulation = $false
            priorityScoring = $false
            skipHeavyComputation = $true
            trigger = 'skip_heavy_computation'
            reason = 'flat_history'
        }
    }

    $hasLineMovement = $false
    $runSimulation = $false
    $priorityScoring = $false
    $maxDeltaDetected = $null
    $lastOddsUpdateTimestamp = $null
    $trigger = 'skip_heavy_computation'
    $reason = 'flat_history'

    foreach ($marketProperty in $markets) {
        $state = $marketProperty.Value
        if ($null -eq $state) {
            continue
        }

        $delta = $state.delta
        if ($null -eq $delta -and $null -ne $state.last_line -and $null -ne $state.previous_line) {
            try {
                $delta = [double]$state.last_line - [double]$state.previous_line
            }
            catch {
                $delta = $null
            }
        }

        if ($null -ne $delta) {
            $hasLineMovement = $true
            $absoluteDelta = [math]::Abs([double]$delta)
            if ($null -eq $maxDeltaDetected -or $absoluteDelta -gt $maxDeltaDetected) {
                $maxDeltaDetected = $absoluteDelta
            }
            if ($absoluteDelta -gt $DeltaThreshold) {
                $runSimulation = $true
                $trigger = 'simulation'
                $reason = 'delta_threshold'
            }
        }

        $history = @($state.history)
        if ($history.Count -ge 2) {
            $lastEntry = $history[-1]
            $previousEntry = $history[-2]
            $lastMovement = [string]$lastEntry.movement
            $previousMovement = [string]$previousEntry.movement
            if (($lastMovement -eq 'up' -or $lastMovement -eq 'down') -and $lastMovement -eq $previousMovement) {
                $priorityScoring = $true
                if (-not $runSimulation) {
                    $trigger = 'priority_scoring'
                    $reason = 'rapid_consecutive_movement'
                }
            }
        }

        $stateUpdatedAt = [string]$state.last_updated
        if (-not [string]::IsNullOrWhiteSpace($stateUpdatedAt)) {
            if ([string]::IsNullOrWhiteSpace($lastOddsUpdateTimestamp) -or $stateUpdatedAt -gt $lastOddsUpdateTimestamp) {
                $lastOddsUpdateTimestamp = $stateUpdatedAt
            }
        }
    }

    if (-not $hasLineMovement) {
        $trigger = 'skip_heavy_computation'
        $reason = 'flat_history'
    }

    $skipHeavyComputation = -not $hasLineMovement
    if (($Sport -eq 'nhl' -or $Sport -eq 'nba' -or $Sport -eq 'wnba') -and $null -ne $scheduleCheck -and $scheduleCheck.known -and [int]$scheduleCheck.count -gt 0) {
        $skipHeavyComputation = $false
        if (-not $runSimulation -and -not $priorityScoring) {
            $trigger = 'scheduled_slate'
            $reason = 'game_present_without_line_movement'
        }
    }

    return [ordered]@{
        sport = $Sport
        workflow = $Workflow
        date = $DateValue
        oddsHistoryPath = $historyPath
        hasLineMovement = $hasLineMovement
        maxDeltaDetected = $maxDeltaDetected
        lastOddsUpdateTimestamp = $lastOddsUpdateTimestamp
        runSimulation = $runSimulation -or $priorityScoring
        priorityScoring = $priorityScoring
        skipHeavyComputation = $skipHeavyComputation
        trigger = $trigger
        reason = $reason
    }
}

function Get-SimExecutionDecision {
    param(
        [string]$RepoRoot,
        [string]$DateValue,
        [string]$LatestManifestPath,
        [string]$LatestCheckpointPath,
        [object[]]$SourceSteps,
        [bool]$SkipSourceUpdates,
        [bool]$ForceRebuildToday
    )

    if ($ForceRebuildToday) {
        return $true
    }

    if ($SkipSourceUpdates) {
        return $false
    }

    if ([string]::IsNullOrWhiteSpace($RepoRoot) -or [string]::IsNullOrWhiteSpace($DateValue)) {
        return $null
    }

    $hasLatestCheckpoint = -not [string]::IsNullOrWhiteSpace($LatestCheckpointPath) -and (Test-Path -LiteralPath $LatestCheckpointPath)

    if (-not (Test-Path -LiteralPath $LatestManifestPath)) {
        if ($hasLatestCheckpoint) {
            return $null
        }
        return $true
    }

    $latestManifest = $null
    try {
        $latestManifest = Get-Content -Path $LatestManifestPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        return $null
    }

    if ($null -eq $latestManifest -or $null -eq $latestManifest.runState) {
        return $true
    }

    foreach ($step in @($SourceSteps)) {
        $sport = [string]$step.Sport
        if ($sport -ne 'nba' -and $sport -ne 'wnba') {
            continue
        }

        $scheduledCheck = Get-BasketballScheduledGamesCheck -Sport $sport -DateValue $DateValue
        if ($null -ne $scheduledCheck -and $scheduledCheck.known -and [int]$scheduledCheck.count -gt 0) {
            return $true
        }
    }

    $oddsHistoryDecisions = @()
    foreach ($step in @($SourceSteps)) {
        $sport = [string]$step.Sport
        $workflow = [string]$step.Workflow
        $decision = Get-OddsHistoryTriggerDecision -RepoRoot $RepoRoot -DateValue $DateValue -Sport $sport -Workflow $workflow
        if ($null -ne $decision) {
            $oddsHistoryDecisions += $decision
        }
    }

    if ($oddsHistoryDecisions.Count -eq 0) {
        return $null
    }

    if (@($oddsHistoryDecisions | Where-Object { [bool]$_.runSimulation -or [bool]$_.priorityScoring }).Count -gt 0) {
        return $true
    }

    if (@($oddsHistoryDecisions | Where-Object { -not [bool]$_.skipHeavyComputation }).Count -eq 0) {
        return $false
    }

    return $null
}

function Get-SimEventArtifactPaths {
    param(
        [string]$RepoRoot,
        [string]$DateValue,
        [string]$Sport,
        [string]$Workflow
    )

    if ([string]::IsNullOrWhiteSpace($RepoRoot) -or [string]::IsNullOrWhiteSpace($DateValue) -or [string]::IsNullOrWhiteSpace($Sport)) {
        return @()
    }

    $paths = New-Object System.Collections.Generic.List[string]
    $slug = $Sport.ToLowerInvariant()

    switch ($slug) {
        'mlb' {
            if ($Workflow -eq 'vendored_daily_update') {
                foreach ($relativePattern in @(
                    "data/mlb_source/data/daily/sims/$DateValue/sim_*.json",
                    "data/mlb_source/source_artifacts/data/daily/sims/$DateValue/sim_*.json"
                )) {
                    $fullPattern = Join-Path $RepoRoot $relativePattern
                    foreach ($match in @(Get-ChildItem -Path $fullPattern -File -ErrorAction SilentlyContinue)) {
                        $paths.Add($match.FullName) | Out-Null
                    }
                }
            }
        }
        'nba' {
            if ($Workflow -eq 'vendored_daily_update') {
                foreach ($relativePattern in @(
                    "data/nba_source/data/processed/smart_sim_${DateValue}_*.json",
                    "data/nba_source/source_artifacts/data/processed/smart_sim_${DateValue}_*.json"
                )) {
                    $fullPattern = Join-Path $RepoRoot $relativePattern
                    foreach ($match in @(Get-ChildItem -Path $fullPattern -File -ErrorAction SilentlyContinue)) {
                        $paths.Add($match.FullName) | Out-Null
                    }
                }
            }
        }
        'wnba' {
            if ($Workflow -eq 'vendored_daily_update') {
                foreach ($relativePattern in @(
                    "data/wnba_source/data/processed/smart_sim_${DateValue}_*.json",
                    "data/wnba_source/source_artifacts/data/processed/smart_sim_${DateValue}_*.json"
                )) {
                    $fullPattern = Join-Path $RepoRoot $relativePattern
                    foreach ($match in @(Get-ChildItem -Path $fullPattern -File -ErrorAction SilentlyContinue)) {
                        $paths.Add($match.FullName) | Out-Null
                    }
                }
            }
        }
        'nhl' {
            if ($Workflow -eq 'vendored_daily_update') {
                foreach ($relativePattern in @(
                    "data/nhl_source/data/processed/smart_sim_${DateValue}_*.json",
                    "data/nhl_source/source_artifacts/data/processed/smart_sim_${DateValue}_*.json"
                )) {
                    $fullPattern = Join-Path $RepoRoot $relativePattern
                    foreach ($match in @(Get-ChildItem -Path $fullPattern -File -ErrorAction SilentlyContinue)) {
                        $paths.Add($match.FullName) | Out-Null
                    }
                }
            }
        }
    }

    return @($paths | Select-Object -Unique)
}

function Get-EventInputFingerprint {
    param(
        [string]$RepoRoot,
        [string]$DateValue,
        [string]$Sport,
        [string]$Workflow
    )

    if ([string]::IsNullOrWhiteSpace($RepoRoot) -or [string]::IsNullOrWhiteSpace($DateValue) -or [string]::IsNullOrWhiteSpace($Sport)) {
        return $null
    }

    $inputPaths = New-Object System.Collections.Generic.List[string]

    function Add-InputPathIfPresent {
        param([string]$RelativePath)

        if ([string]::IsNullOrWhiteSpace($RelativePath)) {
            return
        }

        $fullPath = Join-Path $RepoRoot $RelativePath
        if (Test-Path -LiteralPath $fullPath) {
            $inputPaths.Add((Resolve-Path -LiteralPath $fullPath).Path) | Out-Null
        }
    }

    function Add-InputPathsByPattern {
        param([string]$RelativePattern)

        if ([string]::IsNullOrWhiteSpace($RelativePattern)) {
            return
        }

        foreach ($match in @(Get-ChildItem -Path (Join-Path $RepoRoot $RelativePattern) -File -ErrorAction SilentlyContinue)) {
            $inputPaths.Add($match.FullName) | Out-Null
        }
    }

    $slug = $Sport.ToLowerInvariant()
    switch ($slug) {
        'mlb' {
            if ($Workflow -eq 'vendored_daily_update') {
                foreach ($relativePath in @(
                    "data/mlb_source/data/daily/daily_summary_${DateValue}.json",
                    "data/mlb_source/data/daily/daily_summary_${DateValue}_profile_bundle.json",
                    "data/mlb_source/data/daily/daily_summary_${DateValue}_locked_policy.json",
                    "data/mlb_source/data/daily/daily_summary_${DateValue}_hr_targets.json",
                    "data/mlb_source/data/daily/daily_summary_${DateValue}_rfi_targets.json",
                    "data/mlb_source/data/daily/ladders/daily_ladders_${DateValue}.json",
                    "data/mlb_source/data/daily/top_props/daily_top_props_${DateValue}.json",
                    "data/mlb_source/data/daily/ops/daily_ops_${DateValue}.json",
                    "data/mlb_source/data/daily/snapshots/${DateValue}/lineups.json",
                    "data/mlb_source/data/daily/snapshots/${DateValue}/probables.json",
                    "data/mlb_source/data/daily/snapshots/${DateValue}/oddsapi_game_lines_${DateValue}.json",
                    "data/mlb_source/data/daily/snapshots/${DateValue}/oddsapi_pitcher_props_${DateValue}.json",
                    "data/mlb_source/data/daily/snapshots/${DateValue}/oddsapi_hitter_props_${DateValue}.json",
                    "data/mlb_source/data/live_lens/live_lens_${DateValue}.jsonl",
                    "data/mlb_source/data/live_lens/live_lens_report_${DateValue}.json",
                    "data/mlb_source/data/live_lens/recaps/live_lens_daily_recap_${DateValue}.json",
                    "data/mlb_source/data/live_lens/render_sync/live_lens_reports_${DateValue}.json",
                    "data/mlb_source/data/live_lens/prop_registry/live_prop_registry_${DateValue}.json",
                    "data/mlb_source/data/live_lens/prop_registry/live_prop_registry_${DateValue}.jsonl",
                    "data/mlb_source/data/live_lens/prop_registry/live_prop_observations_${DateValue}.jsonl",
                    "data/mlb_source/data/processed/smart_sim_${DateValue}_*.json",
                    "data/mlb_source/data/processed/team_advanced_stats_*.csv",
                    "data/mlb_source/source_artifacts/data/daily/daily_summary_${DateValue}.json",
                    "data/mlb_source/source_artifacts/data/daily/daily_summary_${DateValue}_profile_bundle.json",
                    "data/mlb_source/source_artifacts/data/daily/daily_summary_${DateValue}_locked_policy.json",
                    "data/mlb_source/source_artifacts/data/daily/daily_summary_${DateValue}_hr_targets.json",
                    "data/mlb_source/source_artifacts/data/daily/daily_summary_${DateValue}_rfi_targets.json",
                    "data/mlb_source/source_artifacts/data/daily/ladders/daily_ladders_${DateValue}.json",
                    "data/mlb_source/source_artifacts/data/daily/top_props/daily_top_props_${DateValue}.json",
                    "data/mlb_source/source_artifacts/data/daily/ops/daily_ops_${DateValue}.json",
                    "data/mlb_source/source_artifacts/data/daily/snapshots/${DateValue}/lineups.json",
                    "data/mlb_source/source_artifacts/data/daily/snapshots/${DateValue}/probables.json",
                    "data/mlb_source/source_artifacts/data/daily/snapshots/${DateValue}/oddsapi_game_lines_${DateValue}.json",
                    "data/mlb_source/source_artifacts/data/daily/snapshots/${DateValue}/oddsapi_pitcher_props_${DateValue}.json",
                    "data/mlb_source/source_artifacts/data/daily/snapshots/${DateValue}/oddsapi_hitter_props_${DateValue}.json",
                    "data/mlb_source/source_artifacts/data/live_lens/live_lens_${DateValue}.jsonl",
                    "data/mlb_source/source_artifacts/data/live_lens/live_lens_report_${DateValue}.json",
                    "data/mlb_source/source_artifacts/data/live_lens/recaps/live_lens_daily_recap_${DateValue}.json",
                    "data/mlb_source/source_artifacts/data/live_lens/render_sync/live_lens_reports_${DateValue}.json",
                    "data/mlb_source/source_artifacts/data/live_lens/prop_registry/live_prop_registry_${DateValue}.json",
                    "data/mlb_source/source_artifacts/data/live_lens/prop_registry/live_prop_registry_${DateValue}.jsonl",
                    "data/mlb_source/source_artifacts/data/live_lens/prop_registry/live_prop_observations_${DateValue}.jsonl",
                    "data/mlb_source/source_artifacts/data/processed/smart_sim_${DateValue}_*.json",
                    "data/mlb_source/source_artifacts/data/processed/team_advanced_stats_*.csv"
                )) {
                    if ($relativePath.Contains('*')) {
                        Add-InputPathsByPattern -RelativePattern $relativePath
                    }
                    else {
                        Add-InputPathIfPresent -RelativePath $relativePath
                    }
                }
            }
        }
        'nba' {
            if ($Workflow -eq 'vendored_daily_update') {
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
                    "data/nba_source/data/processed/props_movement_signals_${DateValue}.csv",
                    "data/nba_source/data/processed/props_recommendations_${DateValue}.csv",
                    "data/nba_source/data/processed/recon_games_${DateValue}.csv",
                    "data/nba_source/data/processed/recon_quarters_${DateValue}.csv",
                    "data/nba_source/data/processed/recon_props_${DateValue}.csv",
                    "data/nba_source/data/processed/recon_players_${DateValue}.csv",
                    "data/nba_source/data/processed/live_player_lens_tuning_${DateValue}.csv",
                    "data/nba_source/data/processed/boxscores_${DateValue}.csv",
                    "data/nba_source/data/processed/live_lens_projections_${DateValue}.jsonl",
                    "data/nba_source/data/processed/live_lens_signals_${DateValue}.jsonl",
                    "data/nba_source/data/processed/live_lens_tuning_override.json",
                    "data/nba_source/data/processed/smart_sim_${DateValue}_*.json",
                    "data/nba_source/data/processed/team_advanced_stats_*.csv",
                    "data/nba_source/data/processed/live_snapshots/live_state_${DateValue}.jsonl",
                    "data/nba_source/data/processed/live_snapshots/live_lines_${DateValue}.jsonl",
                    "data/nba_source/data/processed/live_snapshots/live_pbp_stats_${DateValue}.jsonl",
                    "data/nba_source/data/processed/live_snapshots/live_player_boxscore_${DateValue}.jsonl",
                    "data/nba_source/data/processed/live_snapshots/live_player_lens_${DateValue}.jsonl",
                    "data/nba_source/source_artifacts/data/processed/game_cards_${DateValue}.csv",
                    "data/nba_source/source_artifacts/data/processed/game_odds_${DateValue}.csv",
                    "data/nba_source/source_artifacts/data/processed/recommendations_${DateValue}.csv",
                    "data/nba_source/source_artifacts/data/processed/recommendations_slate_${DateValue}.json",
                    "data/nba_source/source_artifacts/data/processed/cards_sim_detail_${DateValue}.json",
                    "data/nba_source/source_artifacts/data/processed/cards_props_snapshot_${DateValue}.json",
                    "data/nba_source/source_artifacts/data/processed/props_recommendations_top_by_game_${DateValue}.json",
                    "data/nba_source/source_artifacts/data/processed/oddsapi_player_props_${DateValue}.csv",
                    "data/nba_source/source_artifacts/data/processed/props_predictions_${DateValue}.csv",
                    "data/nba_source/source_artifacts/data/processed/props_edges_${DateValue}.csv",
                    "data/nba_source/source_artifacts/data/processed/props_movement_signals_${DateValue}.csv",
                    "data/nba_source/source_artifacts/data/processed/props_recommendations_${DateValue}.csv",
                    "data/nba_source/source_artifacts/data/processed/recon_games_${DateValue}.csv",
                    "data/nba_source/source_artifacts/data/processed/recon_quarters_${DateValue}.csv",
                    "data/nba_source/source_artifacts/data/processed/recon_props_${DateValue}.csv",
                    "data/nba_source/source_artifacts/data/processed/recon_players_${DateValue}.csv",
                    "data/nba_source/source_artifacts/data/processed/live_player_lens_tuning_${DateValue}.csv",
                    "data/nba_source/source_artifacts/data/processed/boxscores_${DateValue}.csv",
                    "data/nba_source/source_artifacts/data/processed/live_lens_projections_${DateValue}.jsonl",
                    "data/nba_source/source_artifacts/data/processed/live_lens_signals_${DateValue}.jsonl",
                    "data/nba_source/source_artifacts/data/processed/live_lens_tuning_override.json",
                    "data/nba_source/source_artifacts/data/processed/smart_sim_${DateValue}_*.json",
                    "data/nba_source/source_artifacts/data/processed/team_advanced_stats_*.csv",
                    "data/nba_source/source_artifacts/data/processed/live_snapshots/live_state_${DateValue}.jsonl",
                    "data/nba_source/source_artifacts/data/processed/live_snapshots/live_lines_${DateValue}.jsonl",
                    "data/nba_source/source_artifacts/data/processed/live_snapshots/live_pbp_stats_${DateValue}.jsonl",
                    "data/nba_source/source_artifacts/data/processed/live_snapshots/live_player_boxscore_${DateValue}.jsonl",
                    "data/nba_source/source_artifacts/data/processed/live_snapshots/live_player_lens_${DateValue}.jsonl"
                )) {
                    if ($relativePath.Contains('*')) {
                        Add-InputPathsByPattern -RelativePattern $relativePath
                    }
                    else {
                        Add-InputPathIfPresent -RelativePath $relativePath
                    }
                }
            }
        }
        'wnba' {
            if ($Workflow -eq 'vendored_daily_update') {
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
                    "data/wnba_source/data/processed/props_movement_signals_${DateValue}.csv",
                    "data/wnba_source/data/processed/props_recommendations_${DateValue}.csv",
                    "data/wnba_source/data/processed/recon_games_${DateValue}.csv",
                    "data/wnba_source/data/processed/recon_quarters_${DateValue}.csv",
                    "data/wnba_source/data/processed/recon_props_${DateValue}.csv",
                    "data/wnba_source/data/processed/recon_players_${DateValue}.csv",
                    "data/wnba_source/data/processed/live_player_lens_tuning_${DateValue}.csv",
                    "data/wnba_source/data/processed/boxscores_${DateValue}.csv",
                    "data/wnba_source/data/processed/live_lens_projections_${DateValue}.jsonl",
                    "data/wnba_source/data/processed/live_lens_signals_${DateValue}.jsonl",
                    "data/wnba_source/data/processed/live_lens_tuning_override.json",
                    "data/wnba_source/data/processed/smart_sim_${DateValue}_*.json",
                    "data/wnba_source/data/processed/team_advanced_stats_*.csv",
                    "data/wnba_source/data/processed/live_snapshots/live_state_${DateValue}.jsonl",
                    "data/wnba_source/data/processed/live_snapshots/live_lines_${DateValue}.jsonl",
                    "data/wnba_source/data/processed/live_snapshots/live_pbp_stats_${DateValue}.jsonl",
                    "data/wnba_source/data/processed/live_snapshots/live_player_boxscore_${DateValue}.jsonl",
                    "data/wnba_source/data/processed/live_snapshots/live_player_lens_${DateValue}.jsonl",
                    "data/wnba_source/source_artifacts/data/processed/game_cards_${DateValue}.csv",
                    "data/wnba_source/source_artifacts/data/processed/game_odds_${DateValue}.csv",
                    "data/wnba_source/source_artifacts/data/processed/recommendations_${DateValue}.csv",
                    "data/wnba_source/source_artifacts/data/processed/recommendations_slate_${DateValue}.json",
                    "data/wnba_source/source_artifacts/data/processed/cards_sim_detail_${DateValue}.json",
                    "data/wnba_source/source_artifacts/data/processed/cards_props_snapshot_${DateValue}.json",
                    "data/wnba_source/source_artifacts/data/processed/props_recommendations_top_by_game_${DateValue}.json",
                    "data/wnba_source/source_artifacts/data/processed/oddsapi_player_props_${DateValue}.csv",
                    "data/wnba_source/source_artifacts/data/processed/props_predictions_${DateValue}.csv",
                    "data/wnba_source/source_artifacts/data/processed/props_edges_${DateValue}.csv",
                    "data/wnba_source/source_artifacts/data/processed/props_movement_signals_${DateValue}.csv",
                    "data/wnba_source/source_artifacts/data/processed/props_recommendations_${DateValue}.csv",
                    "data/wnba_source/source_artifacts/data/processed/recon_games_${DateValue}.csv",
                    "data/wnba_source/source_artifacts/data/processed/recon_quarters_${DateValue}.csv",
                    "data/wnba_source/source_artifacts/data/processed/recon_props_${DateValue}.csv",
                    "data/wnba_source/source_artifacts/data/processed/recon_players_${DateValue}.csv",
                    "data/wnba_source/source_artifacts/data/processed/live_player_lens_tuning_${DateValue}.csv",
                    "data/wnba_source/source_artifacts/data/processed/boxscores_${DateValue}.csv",
                    "data/wnba_source/source_artifacts/data/processed/live_lens_projections_${DateValue}.jsonl",
                    "data/wnba_source/source_artifacts/data/processed/live_lens_signals_${DateValue}.jsonl",
                    "data/wnba_source/source_artifacts/data/processed/live_lens_tuning_override.json",
                    "data/wnba_source/source_artifacts/data/processed/smart_sim_${DateValue}_*.json",
                    "data/wnba_source/source_artifacts/data/processed/team_advanced_stats_*.csv",
                    "data/wnba_source/source_artifacts/data/processed/live_snapshots/live_state_${DateValue}.jsonl",
                    "data/wnba_source/source_artifacts/data/processed/live_snapshots/live_lines_${DateValue}.jsonl",
                    "data/wnba_source/source_artifacts/data/processed/live_snapshots/live_pbp_stats_${DateValue}.jsonl",
                    "data/wnba_source/source_artifacts/data/processed/live_snapshots/live_player_boxscore_${DateValue}.jsonl",
                    "data/wnba_source/source_artifacts/data/processed/live_snapshots/live_player_lens_${DateValue}.jsonl"
                )) {
                    if ($relativePath.Contains('*')) {
                        Add-InputPathsByPattern -RelativePattern $relativePath
                    }
                    else {
                        Add-InputPathIfPresent -RelativePath $relativePath
                    }
                }
            }
        }
        'nhl' {
            if ($Workflow -eq 'vendored_daily_update') {
                foreach ($relativePath in @(
                    "data/nhl_source/data/processed/predictions_${DateValue}.csv",
                    "data/nhl_source/data/processed/predictions_sim_${DateValue}.csv",
                    "data/nhl_source/data/processed/recommendations_${DateValue}.csv",
                    "data/nhl_source/data/processed/recommendations_sim_${DateValue}.csv",
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
                    "data/nhl_source/data/odds/games/date=${DateValue}/scoreboard.csv",
                    "data/nhl_source/data/odds/team/date=${DateValue}/oddsapi.csv",
                    "data/nhl_source/data/odds/team/date=${DateValue}/oddsapi.parquet",
                    "data/nhl_source/data/props/player_props_lines/date=${DateValue}/oddsapi.csv",
                    "data/nhl_source/data/props/player_props_lines/date=${DateValue}/oddsapi.parquet",
                    "data/nhl_source/source_artifacts/data/processed/predictions_${DateValue}.csv",
                    "data/nhl_source/source_artifacts/data/processed/predictions_sim_${DateValue}.csv",
                    "data/nhl_source/source_artifacts/data/processed/recommendations_${DateValue}.csv",
                    "data/nhl_source/source_artifacts/data/processed/recommendations_sim_${DateValue}.csv",
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
                    "data/nhl_source/source_artifacts/data/odds/games/date=${DateValue}/scoreboard.csv",
                    "data/nhl_source/source_artifacts/data/odds/team/date=${DateValue}/oddsapi.csv",
                    "data/nhl_source/source_artifacts/data/odds/team/date=${DateValue}/oddsapi.parquet",
                    "data/nhl_source/source_artifacts/data/props/player_props_lines/date=${DateValue}/oddsapi.csv",
                    "data/nhl_source/source_artifacts/data/props/player_props_lines/date=${DateValue}/oddsapi.parquet"
                )) {
                    if ($relativePath.Contains('*')) {
                        Add-InputPathsByPattern -RelativePattern $relativePath
                    }
                    else {
                        Add-InputPathIfPresent -RelativePath $relativePath
                    }
                }
            }
        }
    }

    $resolvedPaths = @($inputPaths | Sort-Object -Unique)
    if ($resolvedPaths.Count -eq 0) {
        return $null
    }

    $fingerprintParts = New-Object System.Collections.Generic.List[string]
    foreach ($path in $resolvedPaths) {
        try {
            $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash
            $fingerprintParts.Add(($path + '|' + $hash)) | Out-Null
        }
        catch {
        }
    }

    if ($fingerprintParts.Count -eq 0) {
        return $null
    }

    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $payload = [System.Text.Encoding]::UTF8.GetBytes(($fingerprintParts -join [Environment]::NewLine))
        return (([System.BitConverter]::ToString($sha256.ComputeHash($payload))) -replace '-', '').ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
}

function ConvertTo-NullableDateTimeOffset {
    param([object]$Value)

    if ($null -eq $Value) {
        return $null
    }

    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $null
    }

    $parsedOffset = [DateTimeOffset]::MinValue
    if ([DateTimeOffset]::TryParse(
        $text,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AssumeUniversal,
        [ref]$parsedOffset
    )) {
        return $parsedOffset.ToUniversalTime()
    }

    $parsedDateTime = [datetime]::MinValue
    if ([datetime]::TryParse(
        $text,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AssumeUniversal,
        [ref]$parsedDateTime
    )) {
        return ([DateTimeOffset]$parsedDateTime).ToUniversalTime()
    }

    return $null
}

function Get-Policy {
    param(
        [object]$Context,
        [object]$PolicyConfig,
        [object[]]$PolicyPerformance
    )

    if ($null -eq $PolicyConfig) {
        return $null
    }

    $sport = [string]$Context.sport
    $market = [string]$Context.market
    $timeToStartMinutes = $Context.timeToStartMinutes
    $selectedPolicy = $null
    $policySource = $null

    if (-not [string]::IsNullOrWhiteSpace($sport) -and $PolicyConfig.sport -and $PolicyConfig.sport.Contains($sport.ToLowerInvariant())) {
        $selectedPolicy = $PolicyConfig.sport[$sport.ToLowerInvariant()]
        $policySource = 'sport'
    }

    if ($null -eq $selectedPolicy) {
        return $null
    }

    $optimalPolicy = Get-OptimalPolicy -Context $Context -PolicyGroup $selectedPolicy -PolicySource $policySource -PolicyPerformance $PolicyPerformance
    if ($null -eq $optimalPolicy) {
        return $null
    }

    $candidatePolicies = @()
    if ($selectedPolicy.policyCandidates -and @($selectedPolicy.policyCandidates).Count -gt 0) {
        $candidatePolicies = @($selectedPolicy.policyCandidates)
    }
    else {
        $candidatePolicies = @($selectedPolicy)
    }

    $explorationRate = 0.0
    if ($null -ne $selectedPolicy.explorationRate) {
        $explorationRate = [double]$selectedPolicy.explorationRate
    }
    elseif ($null -ne $PolicyConfig.explorationRate) {
        $explorationRate = [double]$PolicyConfig.explorationRate
    }

    if ($explorationRate -gt 0 -and $candidatePolicies.Count -gt 1) {
        $exploreThreshold = [int][math]::Round([math]::Max(0.0, [math]::Min(1.0, $explorationRate)) * 10000)
        if ($exploreThreshold -gt 0 -and (Get-Random -Minimum 0 -Maximum 10000) -lt $exploreThreshold) {
            $explorationCandidates = @($candidatePolicies | Where-Object { [string]$_.policyId -ne [string]$optimalPolicy.policyId })
            if ($explorationCandidates.Count -gt 0) {
                $exploratoryPolicy = $explorationCandidates | Get-Random
                $forceWithinMinutes = if ($null -ne $exploratoryPolicy.forceWithinMinutes) { [int]$exploratoryPolicy.forceWithinMinutes } else { $null }
                return [ordered]@{
                    policyId = [string]$exploratoryPolicy.policyId
                    sport = $sport
                    market = $market
                    timeToStartMinutes = $timeToStartMinutes
                    forceWithinMinutes = $forceWithinMinutes
                    policySource = $policySource
                    selectionMode = 'exploratory'
                    isExploratory = $true
                    explorationRate = $explorationRate
                    optimalPolicyId = [string]$optimalPolicy.policyId
                    keyParameters = [ordered]@{ forceWithinMinutes = $forceWithinMinutes }
                }
            }
        }
    }

    return $optimalPolicy
}

function Get-OptimalPolicy {
    param(
        [object]$Context,
        [object]$PolicyGroup,
        [string]$PolicySource,
        [object[]]$PolicyPerformance
    )

    if ($null -eq $PolicyGroup) {
        return $null
    }

    $sport = [string]$Context.sport
    $market = [string]$Context.market
    $timeToStartMinutes = $Context.timeToStartMinutes
    $minimumSampleSize = 0
    if ($null -ne $PolicyGroup.minimumSampleSize) {
        $minimumSampleSize = [int]$PolicyGroup.minimumSampleSize
    }

    $candidatePolicies = @()
    if ($PolicyGroup.policyCandidates -and @($PolicyGroup.policyCandidates).Count -gt 0) {
        $candidatePolicies = @($PolicyGroup.policyCandidates)
    }
    else {
        $candidatePolicies = @($PolicyGroup)
    }

    $performanceRows = @($PolicyPerformance | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.policyId) })
    if ($performanceRows.Count -eq 0) {
        $defaultCandidate = @($candidatePolicies | Select-Object -First 1)
        if ($defaultCandidate.Count -eq 0) {
            return $null
        }

        $selectedPolicy = $defaultCandidate[0]
        $forceWithinMinutes = if ($null -ne $selectedPolicy.forceWithinMinutes) { [int]$selectedPolicy.forceWithinMinutes } else { $null }
        return [ordered]@{
            policyId = [string]$selectedPolicy.policyId
            sport = $sport
            market = $market
            timeToStartMinutes = $timeToStartMinutes
            forceWithinMinutes = $forceWithinMinutes
            policySource = $PolicySource
            selectionMode = 'default'
            isExploratory = $false
            keyParameters = [ordered]@{ forceWithinMinutes = $forceWithinMinutes }
        }
    }

    $performanceByPolicyId = @{}
    foreach ($row in $performanceRows) {
        $policyId = [string]$row.policyId
        if ([string]::IsNullOrWhiteSpace($policyId)) {
            continue
        }
        $performanceByPolicyId[$policyId] = $row
    }

    $eligibleCandidates = New-Object System.Collections.Generic.List[object]
    foreach ($candidate in $candidatePolicies) {
        $candidatePolicyId = [string]$candidate.policyId
        if ([string]::IsNullOrWhiteSpace($candidatePolicyId)) {
            continue
        }

        $performance = $performanceByPolicyId[$candidatePolicyId]
        if ($null -eq $performance) {
            continue
        }

        $sampleSize = [int]($performance.sampleSize -as [int])
        if ($sampleSize -le 0) {
            $sampleSize = [int]($performance.recordCount -as [int])
        }
        if ($sampleSize -lt $minimumSampleSize) {
            continue
        }

        $roi = $null
        foreach ($roiProperty in @('roi', 'policyRoi', 'performanceRoi')) {
            if ($null -ne $performance.$roiProperty) {
                $roiText = [string]$performance.$roiProperty
                if ([double]::TryParse($roiText, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$roi)) {
                    break
                }
                $roi = $null
            }
        }

        $eligibleCandidates.Add([ordered]@{
            candidate = $candidate
            performance = $performance
            sampleSize = [int]$sampleSize
            roi = $roi
        }) | Out-Null
    }

    if ($eligibleCandidates.Count -eq 0) {
        $defaultCandidate = @($candidatePolicies | Select-Object -First 1)
        if ($defaultCandidate.Count -eq 0) {
            return $null
        }

        $selectedPolicy = $defaultCandidate[0]
        $forceWithinMinutes = if ($null -ne $selectedPolicy.forceWithinMinutes) { [int]$selectedPolicy.forceWithinMinutes } else { $null }
        return [ordered]@{
            policyId = [string]$selectedPolicy.policyId
            sport = $sport
            market = $market
            timeToStartMinutes = $timeToStartMinutes
            forceWithinMinutes = $forceWithinMinutes
            policySource = $PolicySource
            selectionMode = 'default'
            keyParameters = [ordered]@{ forceWithinMinutes = $forceWithinMinutes }
        }
    }

    $bestCandidate = $eligibleCandidates | Sort-Object -Property @{ Expression = { if ($null -ne $_.roi) { [double]$_.roi } else { [double]::MinValue } } ; Descending = $true }, @{ Expression = { [int]$_.sampleSize }; Descending = $true } | Select-Object -First 1
    $bestPolicy = $bestCandidate.candidate
    $bestForceWithinMinutes = if ($null -ne $bestPolicy.forceWithinMinutes) { [int]$bestPolicy.forceWithinMinutes } else { $null }
    return [ordered]@{
        policyId = [string]$bestPolicy.policyId
        sport = $sport
        market = $market
        timeToStartMinutes = $timeToStartMinutes
        forceWithinMinutes = $bestForceWithinMinutes
        policySource = $PolicySource
        selectionMode = 'optimal'
        isExploratory = $false
        keyParameters = [ordered]@{ forceWithinMinutes = $bestForceWithinMinutes }
    }
}

function Select-BestPolicy {
    param(
        [object]$Context,
        [object]$PolicyGroup,
        [string]$PolicySource,
        [object[]]$PolicyPerformance
    )

    return Get-OptimalPolicy -Context $Context -PolicyGroup $PolicyGroup -PolicySource $PolicySource -PolicyPerformance $PolicyPerformance
}

function Get-PolicyPerformance {
    param([object[]]$Records)

    $policyRecords = @($Records | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.policyId) })
    if ($policyRecords.Count -eq 0) {
        return @()
    }

    $performanceRows = New-Object System.Collections.Generic.List[object]
    foreach ($policyGroup in @($policyRecords | Group-Object -Property policyId)) {
        $groupRecords = @($policyGroup.Group)
        $timeSamples = New-Object System.Collections.Generic.List[double]
        $forceSamples = New-Object System.Collections.Generic.List[double]
        $roiSamples = New-Object System.Collections.Generic.List[double]
        $withinWindowCount = 0

        foreach ($record in $groupRecords) {
            $timeSample = $null
            if ($null -ne $record.timeToStartMinutes) {
                $timeSampleText = [string]$record.timeToStartMinutes
                if ([double]::TryParse($timeSampleText, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$timeSample)) {
                    $timeSamples.Add([double]$timeSample) | Out-Null
                }
            }

            $forceSample = $null
            if ($null -ne $record.forceWithinMinutes) {
                $forceSampleText = [string]$record.forceWithinMinutes
                if ([double]::TryParse($forceSampleText, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$forceSample)) {
                    $forceSamples.Add([double]$forceSample) | Out-Null
                }
            }

            $roiSample = $null
            foreach ($roiProperty in @('roi', 'policyRoi', 'performanceRoi')) {
                if ($null -ne $record.$roiProperty) {
                    $roiSampleText = [string]$record.$roiProperty
                    if ([double]::TryParse($roiSampleText, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$roiSample)) {
                        $roiSamples.Add([double]$roiSample) | Out-Null
                    }
                    break
                }
            }

            if ($null -ne $timeSample -and $null -ne $forceSample -and $timeSample -ge 0 -and $timeSample -le $forceSample) {
                $withinWindowCount += 1
            }
        }

        $policySource = [string]($groupRecords | Select-Object -First 1 | ForEach-Object { $_.policySource })
        $keyParameters = @($groupRecords | Select-Object -First 1 | ForEach-Object { $_.policyKeyParameters })
        $exploratoryCount = [int](@($groupRecords | Where-Object { [bool]$_.isExploratory }).Count)
        $performanceRows.Add([ordered]@{
            policyId = [string]$policyGroup.Name
            policySource = $policySource
            keyParameters = if ($keyParameters.Count -gt 0) { $keyParameters[0] } else { $null }
            recordCount = [int]$groupRecords.Count
            sampleSize = [int]$groupRecords.Count
            exploratoryCount = [int]$exploratoryCount
            exploratoryRate = if ($groupRecords.Count -gt 0) { [math]::Round((($exploratoryCount / [double]$groupRecords.Count)), 4) } else { $null }
            plannedCount = [int](@($groupRecords | Where-Object { [string]$_.decision -eq 'planned' }).Count)
            skippedCount = [int](@($groupRecords | Where-Object { [string]$_.decision -eq 'skipped' -or [string]$_.status -eq 'skipped' }).Count)
            dryRunCount = [int](@($groupRecords | Where-Object { [string]$_.status -eq 'dry_run' }).Count)
            withinWindowCount = [int]$withinWindowCount
            averageTimeToStartMinutes = if ($timeSamples.Count -gt 0) { [math]::Round((($timeSamples | Measure-Object -Average).Average), 2) } else { $null }
            averageForceWithinMinutes = if ($forceSamples.Count -gt 0) { [math]::Round((($forceSamples | Measure-Object -Average).Average), 2) } else { $null }
            roi = if ($roiSamples.Count -gt 0) { [math]::Round((($roiSamples | Measure-Object -Average).Average), 4) } else { $null }
        }) | Out-Null
    }

    return $performanceRows.ToArray()
}

function Sync-RunManifestPolicyPerformance {
    param([psobject]$Manifest)

    if ($null -eq $Manifest) {
        return
    }

    $policyPerformance = @(Get-PolicyPerformance -Records @($Manifest.eventSimExecution))
    $Manifest.policyPerformance = $policyPerformance
    if ($Manifest.runPlan) {
        $Manifest.runPlan.policyPerformance = $policyPerformance
    }
    if ($Manifest.statusArtifact -and $Manifest.statusArtifact.state) {
        $Manifest.statusArtifact.state.policyPerformance = $policyPerformance
    }
}

function Get-EventSimExecutionStartTimeUtc {
    param([object]$EventPlan)

    if ($null -eq $EventPlan) {
        return $null
    }

    foreach ($propertyName in @('eventStartTimeUtc', 'startTimeUtc', 'scheduledStartTimeUtc', 'scheduledStartUtc', 'startTime', 'scheduledStartTime')) {
        $candidateStartTime = ConvertTo-NullableDateTimeOffset -Value $EventPlan.$propertyName
        if ($null -ne $candidateStartTime) {
            return $candidateStartTime
        }
    }

    $candidatePaths = New-Object System.Collections.Generic.List[string]
    foreach ($pathValue in @($EventPlan.artifactPath, $EventPlan.inputArtifactPath, $EventPlan.sourceArtifactPath)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$pathValue)) {
            $candidatePaths.Add([string]$pathValue) | Out-Null
        }
    }
    foreach ($pathValue in @($EventPlan.candidateArtifactPaths)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$pathValue)) {
            $candidatePaths.Add([string]$pathValue) | Out-Null
        }
    }

    foreach ($candidatePath in @($candidatePaths | Select-Object -Unique)) {
        if ([string]::IsNullOrWhiteSpace($candidatePath) -or -not (Test-Path -LiteralPath $candidatePath)) {
            continue
        }

        try {
            $content = Get-Content -LiteralPath $candidatePath -Raw -ErrorAction Stop
            $payload = $content | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            continue
        }

        $payloadItems = @()
        if ($payload -is [System.Collections.IEnumerable] -and -not ($payload -is [string])) {
            $payloadItems = @($payload)
        }
        else {
            $payloadItems = @($payload)
        }

        foreach ($payloadItem in $payloadItems) {
            if ($null -eq $payloadItem) {
                continue
            }

            foreach ($propertyName in @('eventStartTimeUtc', 'startTimeUtc', 'scheduledStartTimeUtc', 'scheduledStartUtc', 'start_time_utc', 'start_time_iso', 'start_time', 'startTime', 'commence_time', 'gameDateTimeUTC', 'gameDate')) {
                $candidateStartTime = ConvertTo-NullableDateTimeOffset -Value $payloadItem.$propertyName
                if ($null -ne $candidateStartTime) {
                    return $candidateStartTime
                }
            }

            foreach ($nestedGamesProperty in @('games', 'items', 'events', 'rows')) {
                $nestedGames = @($payloadItem.$nestedGamesProperty)
                foreach ($nestedGame in $nestedGames) {
                    if ($null -eq $nestedGame) {
                        continue
                    }

                    foreach ($propertyName in @('eventStartTimeUtc', 'startTimeUtc', 'scheduledStartTimeUtc', 'scheduledStartUtc', 'start_time_utc', 'start_time_iso', 'start_time', 'startTime', 'commence_time', 'gameDateTimeUTC', 'gameDate')) {
                        $candidateStartTime = ConvertTo-NullableDateTimeOffset -Value $nestedGame.$propertyName
                        if ($null -ne $candidateStartTime) {
                            return $candidateStartTime
                        }
                    }
                }
            }
        }
    }

    return $null
}

function Get-ManifestEventRecordKey {
    param([object]$Record)

    if ($null -eq $Record) {
        return $null
    }

    $sport = [string]$Record.sport
    $workflow = [string]$Record.workflow
    $eventKey = [string]$Record.eventKey
    $artifactPath = [string]$Record.artifactPath

    if ([string]::IsNullOrWhiteSpace($sport) -and [string]::IsNullOrWhiteSpace($workflow) -and [string]::IsNullOrWhiteSpace($eventKey) -and [string]::IsNullOrWhiteSpace($artifactPath)) {
        return $null
    }

    return @($sport, $workflow, $eventKey, $artifactPath) -join '|'
}

function Update-ManifestEventRecordCollection {
    param(
        [object[]]$ExistingRecords,
        [object[]]$NewRecords
    )

    $updatedRecords = New-Object System.Collections.Generic.List[object]
    $indexByKey = @{}

    foreach ($record in @($ExistingRecords)) {
        $recordKey = Get-ManifestEventRecordKey -Record $record
        if ([string]::IsNullOrWhiteSpace($recordKey)) {
            $updatedRecords.Add($record) | Out-Null
            continue
        }

        if (-not $indexByKey.ContainsKey($recordKey)) {
            $indexByKey[$recordKey] = $updatedRecords.Count
            $updatedRecords.Add($record) | Out-Null
        }
    }

    foreach ($record in @($NewRecords)) {
        $recordKey = Get-ManifestEventRecordKey -Record $record
        if ([string]::IsNullOrWhiteSpace($recordKey)) {
            continue
        }

        if ($indexByKey.ContainsKey($recordKey)) {
            $updatedRecords[$indexByKey[$recordKey]] = $record
        }
        else {
            $indexByKey[$recordKey] = $updatedRecords.Count
            $updatedRecords.Add($record) | Out-Null
        }
    }

    if ($updatedRecords.Count -eq 0) {
        return @()
    }

    return @($updatedRecords.ToArray())
}


function Sync-RunManifestEventRecords {
    param(
        [psobject]$Manifest,
        [object[]]$EventRecords,
        [object[]]$ArtifactUpdateRecords
    )

    $Manifest.eventSimExecution = Update-ManifestEventRecordCollection -ExistingRecords @($Manifest.eventSimExecution) -NewRecords $EventRecords
    $Manifest.runPlan.eventSimExecution = Update-ManifestEventRecordCollection -ExistingRecords @($Manifest.runPlan.eventSimExecution) -NewRecords $EventRecords
    $Manifest.artifactUpdates = Update-ManifestEventRecordCollection -ExistingRecords @($Manifest.artifactUpdates) -NewRecords $ArtifactUpdateRecords
    $Manifest.runPlan.artifactUpdates = Update-ManifestEventRecordCollection -ExistingRecords @($Manifest.runPlan.artifactUpdates) -NewRecords $ArtifactUpdateRecords
}

function Get-SimExecutionNoOpDecision {
    param(
        [string]$RepoRoot,
        [string]$DateValue,
        [object[]]$LatestEventSimExecutionPlan
    )

    if ([string]::IsNullOrWhiteSpace($RepoRoot) -or [string]::IsNullOrWhiteSpace($DateValue)) {
        return $null
    }

    $eventPlans = @($LatestEventSimExecutionPlan)
    if ($eventPlans.Count -eq 0) {
        return $null
    }

    $oddsHistoryDecisions = @()
    foreach ($eventPlan in $eventPlans) {
        $sport = [string]$eventPlan.sport
        $workflow = [string]$eventPlan.workflow
        if ([string]::IsNullOrWhiteSpace($sport) -or [string]::IsNullOrWhiteSpace($workflow)) {
            continue
        }

        $artifactPath = [string]$eventPlan.artifactPath
        if (-not [string]::IsNullOrWhiteSpace($artifactPath) -and -not (Test-Path -LiteralPath $artifactPath)) {
            return $true
        }

        $decision = Get-OddsHistoryTriggerDecision -RepoRoot $RepoRoot -DateValue $DateValue -Sport $sport -Workflow $workflow
        if ($null -ne $decision) {
            $oddsHistoryDecisions += $decision
        }
    }

    if ($oddsHistoryDecisions.Count -eq 0) {
        return $null
    }

    if (@($oddsHistoryDecisions | Where-Object { [bool]$_.runSimulation -or [bool]$_.priorityScoring }).Count -gt 0) {
        return $true
    }

    if (@($oddsHistoryDecisions | Where-Object { -not [bool]$_.skipHeavyComputation }).Count -eq 0) {
        return $false
    }

    return $null
}

function Get-EventSimExecutionDecision {
    param(
        [object]$CurrentFingerprint,
        [object]$PreviousFingerprint,
        [object]$Fallback,
        [object]$CurrentTimeUtc,
        [object]$EventStartTimeUtc,
        [string]$ArtifactPath,
        [int]$ForceWithinMinutes = 30
    )

    $currentFingerprintText = [string]$CurrentFingerprint
    $previousFingerprintText = [string]$PreviousFingerprint
    $currentTimeOffset = ConvertTo-NullableDateTimeOffset -Value $CurrentTimeUtc
    $eventStartOffset = ConvertTo-NullableDateTimeOffset -Value $EventStartTimeUtc

    if ($null -ne $currentTimeOffset -and $null -ne $eventStartOffset -and $ForceWithinMinutes -gt 0) {
        $windowStartOffset = $eventStartOffset.AddMinutes(-1 * [double]$ForceWithinMinutes)
        if ($currentTimeOffset -ge $windowStartOffset -and $currentTimeOffset -le $eventStartOffset) {
            return $true
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($ArtifactPath) -and -not (Test-Path -LiteralPath $ArtifactPath)) {
        return $true
    }

    if ([string]::IsNullOrWhiteSpace($currentFingerprintText)) {
        return $Fallback
    }

    if ([string]::IsNullOrWhiteSpace($previousFingerprintText)) {
        return $true
    }

    if ($currentFingerprintText -eq $previousFingerprintText) {
        return $false
    }

    return $true
}

function Get-SimEventArtifactPaths {
    param(
        [string]$RepoRoot,
        [string]$DateValue,
        [string]$Sport,
        [string]$Workflow
    )

    if ([string]::IsNullOrWhiteSpace($RepoRoot) -or [string]::IsNullOrWhiteSpace($DateValue) -or [string]::IsNullOrWhiteSpace($Sport)) {
        return @()
    }

    $paths = New-Object System.Collections.Generic.List[string]
    $sportSlug = $Sport.ToLowerInvariant()

    switch ($sportSlug) {
        'mlb' {
            if ($Workflow -eq 'vendored_daily_update') {
                foreach ($relativePattern in @(
                    "data/mlb_source/data/daily/sims/$DateValue/sim_*.json",
                    "data/mlb_source/source_artifacts/data/daily/sims/$DateValue/sim_*.json"
                )) {
                    $fullPattern = Join-Path $RepoRoot $relativePattern
                    foreach ($match in @(Get-ChildItem -Path $fullPattern -File -ErrorAction SilentlyContinue)) {
                        $paths.Add($match.FullName) | Out-Null
                    }
                }
            }
        }
        'nba' {
            if ($Workflow -eq 'vendored_daily_update') {
                foreach ($relativePattern in @(
                    "data/nba_source/data/processed/smart_sim_${DateValue}_*.json",
                    "data/nba_source/source_artifacts/data/processed/smart_sim_${DateValue}_*.json"
                )) {
                    $fullPattern = Join-Path $RepoRoot $relativePattern
                    foreach ($match in @(Get-ChildItem -Path $fullPattern -File -ErrorAction SilentlyContinue)) {
                        $paths.Add($match.FullName) | Out-Null
                    }
                }
            }
        }
        'wnba' {
            if ($Workflow -eq 'vendored_daily_update') {
                foreach ($relativePattern in @(
                    "data/wnba_source/data/processed/smart_sim_${DateValue}_*.json",
                    "data/wnba_source/source_artifacts/data/processed/smart_sim_${DateValue}_*.json"
                )) {
                    $fullPattern = Join-Path $RepoRoot $relativePattern
                    foreach ($match in @(Get-ChildItem -Path $fullPattern -File -ErrorAction SilentlyContinue)) {
                        $paths.Add($match.FullName) | Out-Null
                    }
                }
            }
        }
        'nhl' {
            if ($Workflow -eq 'vendored_daily_update') {
                foreach ($relativePattern in @(
                    "data/nhl_source/data/processed/smart_sim_${DateValue}_*.json",
                    "data/nhl_source/source_artifacts/data/processed/smart_sim_${DateValue}_*.json"
                )) {
                    $fullPattern = Join-Path $RepoRoot $relativePattern
                    foreach ($match in @(Get-ChildItem -Path $fullPattern -File -ErrorAction SilentlyContinue)) {
                        $paths.Add($match.FullName) | Out-Null
                    }
                }
            }
        }
    }

    return @($paths | Select-Object -Unique)
}

function Get-SimEventArtifactsFromManifest {
    param(
        [object]$Manifest,
        [string]$Sport,
        [string]$Workflow
    )

    if ($null -eq $Manifest -or [string]::IsNullOrWhiteSpace($Sport)) {
        return @()
    }

    $records = @($Manifest.eventSimExecution)
    if ($records.Count -eq 0) {
        return @()
    }

    return @(
        $records |
            Where-Object { [string]$_.sport -eq $Sport -and ([string]::IsNullOrWhiteSpace($Workflow) -or [string]$_.workflow -eq $Workflow) } |
            ForEach-Object {
                [ordered]@{
                    sport = [string]$_.sport
                    workflow = [string]$_.workflow
                    eventKey = [string]$_.eventKey
                    candidateArtifactPaths = @($_.candidateArtifactPaths)
                    inputFingerprint = [string]$_.inputFingerprint
                    eventStartTimeUtc = [string]$_.eventStartTimeUtc
                }
            }
    )
}

function Get-ActiveMlbUiDailyLocks {
    param(
        [string]$MlbDataRoot,
        [string]$DateValue,
        [string]$SeasonValue
    )

    if ([string]::IsNullOrWhiteSpace($MlbDataRoot) -or [string]::IsNullOrWhiteSpace($DateValue) -or [string]::IsNullOrWhiteSpace($SeasonValue)) {
        return @()
    }

    $lockDir = Join-Path $MlbDataRoot 'runtime\locks'
    if (-not (Test-Path $lockDir)) {
        return @()
    }

    $activeLocks = @()
    $pattern = "daily_update_ui-daily_{0}_{1}_*.lock" -f $SeasonValue, $DateValue
    foreach ($lockFile in @(Get-ChildItem -Path $lockDir -File -Filter $pattern -ErrorAction SilentlyContinue)) {
        $lockPayload = $null
        $lockPid = $null
        try {
            $lockPayload = Get-Content -Path $lockFile.FullName -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
            if ($null -ne $lockPayload.pid) {
                $lockPid = [int]$lockPayload.pid
            }
        }
        catch {
            $lockPayload = $null
            $lockPid = $null
        }

        if ($null -ne $lockPid -and (Test-ProcessIdRunning -ProcessId $lockPid)) {
            $activeLocks += @([pscustomobject]@{
                pid = $lockPid
                path = $lockFile.FullName
                createdAt = if ($null -ne $lockPayload -and $null -ne $lockPayload.created_at) { [string]$lockPayload.created_at } else { $null }
                command = if ($null -ne $lockPayload -and $null -ne $lockPayload.command) { @($lockPayload.command) } else { @() }
            })
        }
    }

    return @($activeLocks)
}

function Wait-ForMlbUiDailyLockRelease {
    param(
        [string]$MlbDataRoot,
        [string]$DateValue,
        [string]$SeasonValue,
        [int]$TimeoutSeconds = 3600,
        [int]$PollSeconds = 20,
        [bool]$FailFastOnActiveLock = $true
    )

    if ([string]::IsNullOrWhiteSpace($MlbDataRoot) -or [string]::IsNullOrWhiteSpace($DateValue) -or [string]::IsNullOrWhiteSpace($SeasonValue)) {
        return
    }

    $safeTimeout = [Math]::Max(1, [int]$TimeoutSeconds)
    $safePoll = [Math]::Max(1, [int]$PollSeconds)
    $deadline = (Get-Date).AddSeconds($safeTimeout)

    while ($true) {
        $activeLocks = @(Get-ActiveMlbUiDailyLocks -MlbDataRoot $MlbDataRoot -DateValue $DateValue -SeasonValue $SeasonValue)
        $activeCount = $activeLocks.Count
        if ($activeCount -le 0) {
            return
        }

        if ($FailFastOnActiveLock) {
            $lockSummary = @(
                $activeLocks | ForEach-Object {
                    $parts = @("pid=$($_.pid)", "path=$($_.path)")
                    if (-not [string]::IsNullOrWhiteSpace([string]$_.createdAt)) {
                        $parts += "created_at=$($_.createdAt)"
                    }
                    if ($_.command.Count -gt 0) {
                        $parts += ("command={0}" -f ($_.command -join ' '))
                    }
                    $parts -join '; '
                }
            ) -join ' | '
            throw "MLB ui-daily run already active for $DateValue; refusing duplicate daily update. $lockSummary"
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

    # ✅ FIRST: respect CI-provided Python
    if ($env:PYTHON_PATH -and (Test-Path $env:PYTHON_PATH)) {
        return $env:PYTHON_PATH
    }

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
            $advancedFiles = @(Get-ChildItem -Path $processedRoot -File -Filter 'team_advanced_stats_*.csv' -ErrorAction SilentlyContinue)
            if ($advancedFiles.Count -eq 0) {
                throw 'NBA advanced-data gate failed: missing mirrored team_advanced_stats artifacts'
            }
            if ($smartSimFiles.Count -gt 0) {
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
            }
            else {
                $liveLensProjections = @(Get-ChildItem -Path $processedRoot -File -Filter ("live_lens_projections_{0}.jsonl" -f $DateValue) -ErrorAction SilentlyContinue)
                if ($liveLensProjections.Count -eq 0) {
                    throw "NBA advanced-data gate failed: missing live_lens projections artifacts for $DateValue"
                }
                $liveSnapshotRoot = Join-Path $processedRoot 'live_snapshots'
                $liveLinesFiles = @(Get-ChildItem -Path $liveSnapshotRoot -File -Filter ("live_lines_{0}.jsonl" -f $DateValue) -ErrorAction SilentlyContinue)
                $livePlayerLensFiles = @(Get-ChildItem -Path $liveSnapshotRoot -File -Filter ("live_player_lens_{0}.jsonl" -f $DateValue) -ErrorAction SilentlyContinue)
                if ($liveLinesFiles.Count -eq 0 -or $livePlayerLensFiles.Count -eq 0) {
                    throw "NBA advanced-data gate failed: missing live snapshot artifacts for $DateValue"
                }
                $foundUsableLiveLensPayload = $false
                foreach ($projectionFile in $liveLensProjections) {
                    try {
                        $projectionLines = @(Get-Content -Path $projectionFile.FullName -ErrorAction Stop)
                        foreach ($projectionLine in $projectionLines) {
                            if ([string]::IsNullOrWhiteSpace($projectionLine)) {
                                continue
                            }
                            $projection = $projectionLine | ConvertFrom-Json -ErrorAction Stop
                            if (($null -ne $projection.proj) -or ($null -ne $projection.sim_mu) -or ($null -ne $projection.strength)) {
                                $foundUsableLiveLensPayload = $true
                                break
                            }
                        }
                        if ($foundUsableLiveLensPayload) {
                            break
                        }
                    }
                    catch {
                    }
                }
                if (-not $foundUsableLiveLensPayload) {
                    throw "NBA advanced-data gate failed: live_lens projections were empty for $DateValue"
                }
            }
            return
        }
        'wnba' {
            $scheduleCheck = Get-BasketballScheduledGamesCheck -Sport 'wnba' -DateValue $DateValue
            $scheduledGameCount = if ($scheduleCheck.known -and $null -ne $scheduleCheck.count) { [int]$scheduleCheck.count } else { $null }
            $requireSmartSimArtifacts = ($null -eq $scheduledGameCount) -or ($scheduledGameCount -gt 0)
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
                    Write-Host "WNBA advanced-data gate skipped: missing $requiredArtifact" -ForegroundColor Yellow
                    return
                }
            }

            $smartSimFiles = @()
            if ($requireSmartSimArtifacts) {
                $smartSimFiles = @(Get-ChildItem -Path $processedRoot -File -Filter ("smart_sim_{0}_*.json" -f $DateValue) -ErrorAction SilentlyContinue)
                if ($smartSimFiles.Count -eq 0) {
                    throw "WNBA advanced-data gate failed: missing smart_sim artifacts for $DateValue"
                }
            }
            $advancedFiles = @(Get-ChildItem -Path $processedRoot -File -Filter 'team_advanced_stats_*.csv' -ErrorAction SilentlyContinue)
            if ($advancedFiles.Count -eq 0) {
                throw 'WNBA advanced-data gate failed: missing mirrored team_advanced_stats artifacts'
            }
            $foundNonBaselinePace = $false
            $foundUsableSmartSimPayload = $false
            if ($requireSmartSimArtifacts) {
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
                Write-Host "MLB advanced-data gate skipped: missing artifacts for $DateValue" -ForegroundColor Yellow
                 return
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

            $inCI = $env:GITHUB_ACTIONS -eq "true"

            
            if ([string]::IsNullOrWhiteSpace($processedRoot)) {
                if ($inCI) {
                    Write-Host ("NHL advanced-data gate skipped in CI: missing processed root: {0}" -f ($processedRootCandidates -join '; ')) -ForegroundColor Yellow
                    return
                }
                else {
                     throw ("NHL advanced-data gate failed: missing required artifacts in any processed root: {0}" -f ($processedRootCandidates -join '; '))
                }
            }
            $lineupsPath = Join-Path $processedRoot ("lineups_{0}.csv" -f $DateValue)

            $smartSimFiles = @(Get-ChildItem -Path $processedRoot -File -Filter ("smart_sim_{0}_*.json" -f $DateValue) -ErrorAction SilentlyContinue)
            if ($smartSimFiles.Count -eq 0) { 
                if ($inCI) {
                    Write-Host "NHL advanced-data gate skipped in CI: missing smart_sim artifacts for $DateValue" -ForegroundColor Yellow
                    return
                }
                else {
                    throw "NHL advanced-data gate failed: missing smart_sim artifacts for $DateValue"
                }
            }

            if (Test-NhlPlaceholderLineupProfile -LineupsCsvPath $lineupsPath) {   
                if ($inCI) {
                    Write-Host "NHL advanced-data gate skipped in CI: placeholder lineup profile detected in $lineupsPath" -ForegroundColor Yellow
                    return
                }
                else {
                    throw "NHL advanced-data gate failed: placeholder lineup profile detected in $lineupsPath"
                }
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

function Get-PublishParitySummary {
    param(
        [string]$DateValue,
        [string[]]$ForcedPublishArtifactPaths,
        [string[]]$IntelligencePublishArtifactPaths
    )

    $forcedPaths = @(
        $ForcedPublishArtifactPaths |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            ForEach-Object { ([string]$_).Trim().Replace('\', '/') } |
            Select-Object -Unique
    )
    $intelligencePaths = @(
        $IntelligencePublishArtifactPaths |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            ForEach-Object { ([string]$_).Trim().Replace('\', '/') } |
            Select-Object -Unique
    )

    $sportPrefixes = [ordered]@{
        mlb = 'data/mlb_source/'
        nba = 'data/nba_source/'
        wnba = 'data/wnba_source/'
        nhl = 'data/nhl_source/'
        nfl = 'data/nfl_source/'
        ncaaf = 'data/ncaaf_source/'
        ncaab = 'data/ncaab_source/'
    }

    $sports = @()
    foreach ($entry in $sportPrefixes.GetEnumerator()) {
        $prefix = [string]$entry.Value
        $forcedCount = @($forcedPaths | Where-Object { $_.StartsWith($prefix) -or $_.Contains("/$prefix") }).Count
        $intelligenceCount = @($intelligencePaths | Where-Object { $_.StartsWith($prefix) -or $_.Contains("/$prefix") }).Count
        $totalCount = @(
            ($forcedPaths + $intelligencePaths) |
                Where-Object { $_.StartsWith($prefix) -or $_.Contains("/$prefix") } |
                Select-Object -Unique
        ).Count

        $sports += [ordered]@{
            sport = [string]$entry.Key
            rootPrefix = $prefix
            forcedPublishPathCount = $forcedCount
            intelligencePublishPathCount = $intelligenceCount
            totalPublishPathCount = $totalCount
        }
    }

    return [ordered]@{
        generatedAt = (Get-Date).ToUniversalTime().ToString('o')
        date = if ([string]::IsNullOrWhiteSpace($DateValue)) { $null } else { [string]$DateValue.Trim() }
        totalForcedPublishPaths = $forcedPaths.Count
        totalIntelligencePublishPaths = $intelligencePaths.Count
        totalPublishPaths = @($forcedPaths + $intelligencePaths | Select-Object -Unique).Count
        sports = @($sports)
    }
}

function New-PublishParitySummary {
    param(
        [string]$DateValue,
        [bool]$SkipGitPush,
        [string[]]$ForcedPublishArtifactPaths,
        [string[]]$IntelligencePublishArtifactPaths
    )

    if ($SkipGitPush) {
        return [ordered]@{
            date = $DateValue
            skipped = $true
            forcedPublishArtifactPathCount = 0
            intelligencePublishArtifactPathCount = 0
            missingForcedPublishArtifactPaths = @()
            missingIntelligencePublishArtifactPaths = @()
            status = 'skipped'
        }
    }

    return Get-PublishParitySummary -DateValue $DateValue -ForcedPublishArtifactPaths $ForcedPublishArtifactPaths -IntelligencePublishArtifactPaths $IntelligencePublishArtifactPaths
}

function Get-ForcedPublishArtifactPaths {
    param(
        [string]$RepoPath,
        [string]$DateValue,
        [bool]$SkipGitPush,
        [bool]$SkipMLB,
        [bool]$SkipNBA,
        [bool]$SkipNHL,
        [bool]$SkipWNBA,
        [bool]$SkipNFL,
        [bool]$SkipNCAAF,
        [bool]$SkipNCAAB
    )

    if ($SkipGitPush) {
        return @()
    }

    $paths = [System.Collections.Generic.List[string]]::new()
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

        $pendingRoots = [System.Collections.Generic.List[string]]::new()
        $visitedRoots = @{}
        $pendingRoots.Add($fullRoot) | Out-Null

        for ($index = 0; $index -lt $pendingRoots.Count; $index++) {
            $currentRoot = $pendingRoots[$index]
            if ([string]::IsNullOrWhiteSpace($currentRoot) -or $visitedRoots.ContainsKey($currentRoot)) {
                continue
            }
            $visitedRoots[$currentRoot] = $true

            foreach ($match in @(Get-ChildItem -LiteralPath $currentRoot -File -ErrorAction SilentlyContinue)) {
                $relativePath = $match.FullName.Substring($RepoPath.Length).TrimStart('\', '/') -replace '\\', '/'
                if (-not [string]::IsNullOrWhiteSpace($relativePath)) {
                    $paths.Add($relativePath) | Out-Null
                }
            }

            foreach ($childRoot in @(Get-ChildItem -LiteralPath $currentRoot -Directory -ErrorAction SilentlyContinue)) {
                try {
                    if (($childRoot.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                        continue
                    }
                }
                catch {
                    continue
                }
                $childPath = $childRoot.FullName
                if (-not [string]::IsNullOrWhiteSpace($childPath) -and -not $visitedRoots.ContainsKey($childPath)) {
                    $pendingRoots.Add($childPath) | Out-Null
                }
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

    function Add-BasketballPublishPaths {
        param(
            [string]$SportRootRelative,
            [switch]$IncludeSeasonBettingCards
        )

        if ([string]::IsNullOrWhiteSpace($SportRootRelative)) {
            return
        }

        $sportSlug = ($SportRootRelative.TrimEnd('/', '\') -split '[\\/]')[-1].Replace('_source', '').ToLowerInvariant()

        foreach ($rootRelative in @(
            $SportRootRelative.TrimEnd('/', '\'),
            ($SportRootRelative.TrimEnd('/', '\') + '/source_artifacts')
        )) {
            foreach ($relativePath in @(
                "${rootRelative}/data/processed/game_cards_${DateValue}.csv",
                "${rootRelative}/data/processed/game_odds_${DateValue}.csv",
                "${rootRelative}/data/processed/recommendations_${DateValue}.csv",
                "${rootRelative}/data/processed/recommendations_slate_${DateValue}.json",
                "${rootRelative}/data/processed/cards_sim_detail_${DateValue}.json",
                "${rootRelative}/data/processed/cards_props_snapshot_${DateValue}.json",
                "${rootRelative}/data/processed/props_recommendations_top_by_game_${DateValue}.json",
                "${rootRelative}/data/processed/oddsapi_player_props_${DateValue}.csv",
                "${rootRelative}/data/processed/props_predictions_${DateValue}.csv",
                "${rootRelative}/data/processed/props_edges_${DateValue}.csv",
                "${rootRelative}/data/processed/props_movement_signals_${DateValue}.csv",
                "${rootRelative}/data/processed/props_recommendations_${DateValue}.csv",
                "${rootRelative}/data/processed/recon_games_${DateValue}.csv",
                "${rootRelative}/data/processed/recon_quarters_${DateValue}.csv",
                "${rootRelative}/data/processed/recon_props_${DateValue}.csv",
                "${rootRelative}/data/processed/recon_players_${DateValue}.csv",
                "${rootRelative}/data/processed/live_player_lens_tuning_${DateValue}.csv",
                "${rootRelative}/data/processed/boxscores_${DateValue}.csv",
                "${rootRelative}/data/processed/live_lens_projections_${DateValue}.jsonl",
                "${rootRelative}/data/processed/live_lens_signals_${DateValue}.jsonl",
                "${rootRelative}/data/processed/live_lens_tuning_override.json",
                "${rootRelative}/data/processed/live_snapshots/live_state_${DateValue}.jsonl",
                "${rootRelative}/data/processed/live_snapshots/live_lines_${DateValue}.jsonl",
                "${rootRelative}/data/processed/live_snapshots/live_pbp_stats_${DateValue}.jsonl",
                "${rootRelative}/data/processed/live_snapshots/live_player_boxscore_${DateValue}.jsonl",
                "${rootRelative}/data/processed/live_snapshots/live_player_lens_${DateValue}.jsonl",
                "${rootRelative}/data/live_lens/live_lens_projections_${DateValue}.jsonl",
                "${rootRelative}/data/live_lens/live_lens_signals_${DateValue}.jsonl",
                "${rootRelative}/data/live_lens/live_lens_tuning_override.json",
                "${rootRelative}/tracking/odds_history.json",
                "${rootRelative}/artifacts/${sportSlug}/odds_history.json"
            )) {
                Add-PathIfPresent -RelativePath $relativePath
            }

            Add-PathsUnderRoot -RelativeRoot "${rootRelative}/manifests"

            foreach ($relativePath in @(
                "${rootRelative}/data/raw/odds_${sportSlug}_player_props_${DateValue}.csv",
                "${rootRelative}/data/raw/odds_${sportSlug}_player_props_opening_${DateValue}.csv",
                "${rootRelative}/data/raw/odds_${sportSlug}_player_props_history_${DateValue}.csv"
            )) {
                Add-PathIfPresent -RelativePath $relativePath
            }

            Add-PathsByPattern -RelativePattern "${rootRelative}/data/processed/smart_sim_${DateValue}_*.json"
            Add-PathsByPattern -RelativePattern "${rootRelative}/data/processed/team_advanced_stats_*.csv"
            if ($IncludeSeasonBettingCards) {
                Add-PathsByPattern -RelativePattern "${rootRelative}/data/processed/season_betting_card_manifest_*_retuned_${DateValue}.json"
                Add-PathsByPattern -RelativePattern "${rootRelative}/data/processed/season_betting_card_manifest_*_retuned.json"
                Add-PathsByPattern -RelativePattern "${rootRelative}/data/processed/season_betting_card_day_*_retuned_${DateValue}.json"
                Add-PathsByPattern -RelativePattern "${rootRelative}/data/processed/season_betting_card_day_*_retuned_${DateValue}_insights.json"
            }
            Add-DateGameBoxscoreCachePaths -GameCardsRelativePath "${rootRelative}/data/processed/game_cards_${DateValue}.csv" -BoxscoreRelativeRoot "${rootRelative}/data/processed/boxscores"
            Add-PathsUnderRoot -RelativeRoot "${rootRelative}/source_artifacts/manifests"
        }
    }

    if (-not $SkipMLB) {
        foreach ($rootRelative in @('data/mlb_source/data', 'data/mlb_source/source_artifacts/data')) {
            foreach ($relativePath in @(
                "$rootRelative/daily/daily_summary_${dateSlug}.json",
                "$rootRelative/daily/daily_summary_${dateSlug}_profile_bundle.json",
                "$rootRelative/daily/daily_summary_${dateSlug}_locked_policy.json",
                "$rootRelative/daily/daily_summary_${dateSlug}_hr_targets.json",
                "$rootRelative/daily/daily_summary_${dateSlug}_rfi_targets.json",
                "$rootRelative/daily/ladders/daily_ladders_${dateSlug}.json",
                "$rootRelative/daily/top_props/daily_top_props_${dateSlug}.json",
                "$rootRelative/daily/ops/daily_ops_${dateSlug}.json",
                "$rootRelative/daily/snapshots/${DateValue}/lineups.json",
                "$rootRelative/daily/snapshots/${DateValue}/probables.json",
                "$rootRelative/daily/snapshots/${DateValue}/oddsapi_game_lines_${dateSlug}.json",
                "$rootRelative/daily/snapshots/${DateValue}/oddsapi_pitcher_props_${dateSlug}.json",
                "$rootRelative/daily/snapshots/${DateValue}/oddsapi_hitter_props_${dateSlug}.json",
                "$rootRelative/live_lens/live_lens_${dateSlug}.jsonl",
                "$rootRelative/live_lens/live_lens_report_${dateSlug}.json",
                "$rootRelative/live_lens/recaps/live_lens_daily_recap_${dateSlug}.json",
                "$rootRelative/live_lens/render_sync/live_lens_reports_${dateSlug}.json",
                "$rootRelative/live_lens/prop_registry/live_prop_registry_${dateSlug}.json",
                "$rootRelative/live_lens/prop_registry/live_prop_registry_${dateSlug}.jsonl",
                "$rootRelative/live_lens/prop_registry/live_prop_observations_${dateSlug}.jsonl",
                "$rootRelative/tuning/live_prop_ranking/default.json",
                "$rootRelative/../sim_engine/live_prop_ranking.py"
            )) {
                Add-PathIfPresent -RelativePath $relativePath
            }

            Add-PathsByPattern -RelativePattern "$rootRelative/daily/sims/${DateValue}/sim_*.json"
            Add-PathsByPattern -RelativePattern "$rootRelative/daily/season_frontend/season_manifest_*_${dateSlug}.json"
            Add-PathsByPattern -RelativePattern "$rootRelative/daily/season_frontend/season_day_*_${dateSlug}_*.json"
            Add-PathsByPattern -RelativePattern "$rootRelative/daily/season_frontend/season_betting_day_*_${dateSlug}_*.json"
            Add-PathsByPattern -RelativePattern "$rootRelative/daily/season_frontend/season_official_betting_day_*_${dateSlug}_*.json"
            Add-PathsByPattern -RelativePattern "$rootRelative/eval/seasons/*/season_eval_manifest.json"
            Add-PathsByPattern -RelativePattern "$rootRelative/eval/seasons/*/season_betting_cards_retuned_manifest.json"
            Add-PathsByPattern -RelativePattern "$rootRelative/eval/seasons/*/season_betting_cards_retuned_hrr_manifest.json"
            Add-PathsByPattern -RelativePattern "$rootRelative/eval/seasons/*/betting_day_payloads*/season_betting_day_*_${dateSlug}*.json"
            Add-PathsByPattern -RelativePattern "$rootRelative/eval/seasons/*/betting_day_recaps*/season_betting_day_*_${dateSlug}*.json"
            Add-PathsUnderRoot -RelativeRoot "$rootRelative/../tracking"
        }

        Add-PathsUnderRoot -RelativeRoot 'data/mlb_source/manifests'
        Add-PathsUnderRoot -RelativeRoot 'data/mlb_source/source_artifacts/manifests'
    }

    if (-not $SkipNBA) {
        Add-BasketballPublishPaths -SportRootRelative 'data/nba_source' -IncludeSeasonBettingCards
    }

    if (-not $SkipWNBA) {
        Add-BasketballPublishPaths -SportRootRelative 'data/wnba_source' -IncludeSeasonBettingCards
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
        Add-PathsUnderRoot -RelativeRoot 'data/nhl_source/tracking'
    }

    if (-not $SkipNFL) {
        foreach ($relativePath in @(
            'data/nfl_source/current_week.json',
            'data/nfl_source/calibration_active.json',
            'data/nfl_source/prob_calibration.json',
            'data/nfl_source/sigma_calibration.json',
            'data/nfl_source/totals_calibration.json',
            'data/nfl_source/source_artifacts/current_week.json',
            'data/nfl_source/source_artifacts/calibration_active.json',
            'data/nfl_source/source_artifacts/prob_calibration.json',
            'data/nfl_source/source_artifacts/sigma_calibration.json',
            'data/nfl_source/source_artifacts/totals_calibration.json'
        )) {
            Add-PathIfPresent -RelativePath $relativePath
        }

        Add-PathsByPattern -RelativePattern 'data/nfl_source/upcoming_recs_*.csv'
        Add-PathsByPattern -RelativePattern 'data/nfl_source/oddsapi_player_props_*.csv'
        Add-PathsByPattern -RelativePattern 'data/nfl_source/source_artifacts/upcoming_recs_*.csv'
        Add-PathsByPattern -RelativePattern 'data/nfl_source/source_artifacts/oddsapi_player_props_*.csv'
        Add-PathsUnderRoot -RelativeRoot 'data/nfl_source/manifests'
        Add-PathsUnderRoot -RelativeRoot 'data/nfl_source/source_artifacts/manifests'
        Add-PathsUnderRoot -RelativeRoot 'data/nfl_source/tracking'
    }

    if (-not $SkipNCAAF) {
        foreach ($relativePath in @(
            'data/ncaaf_source/data/recommendations_latest.json',
            'data/ncaaf_source/source_artifacts/recommendations_latest.json'
        )) {
            Add-PathIfPresent -RelativePath $relativePath
        }

        Add-PathsByPattern -RelativePattern 'data/ncaaf_source/data/recommendations_summary/*.json'
        Add-PathsByPattern -RelativePattern 'data/ncaaf_source/source_artifacts/recommendations_summary/*.json'
        Add-PathsByPattern -RelativePattern 'data/ncaaf_source/data/college_football_schedule_*_predicted_totals_enhanced*.csv'
        Add-PathsByPattern -RelativePattern 'data/ncaaf_source/source_artifacts/college_football_schedule_*_predicted_totals_enhanced*.csv'
        Add-PathsByPattern -RelativePattern 'data/ncaaf_source/data/recommendations_*.csv'
        Add-PathsByPattern -RelativePattern 'data/ncaaf_source/source_artifacts/recommendations_*.csv'
        Add-PathsUnderRoot -RelativeRoot 'data/ncaaf_source/data/manifests'
        Add-PathsUnderRoot -RelativeRoot 'data/ncaaf_source/source_artifacts/manifests'
        Add-PathsUnderRoot -RelativeRoot 'data/ncaaf_source/tracking'
    }

    if (-not $SkipNCAAB) {
        foreach ($relativePath in @(
            "data/ncaab_source/api/recommendations/recommendations_${DateValue}.json",
            "data/ncaab_source/api/live_state/live_state_${DateValue}.json",
            "data/ncaab_source/api/live_lines/live_lines_${DateValue}.json"
        )) {
            Add-PathIfPresent -RelativePath $relativePath
        }
        Add-PathsUnderRoot -RelativeRoot 'data/ncaab_source/tracking'
    }

    return @($paths | Select-Object -Unique)
}

function Invoke-GitPublish {
    param(
        [string]$Name,
        [string]$RepoPath,
        [string]$CommitMessage,
        [string]$RemoteName,
        [string[]]$ForceIncludePaths = @(),
        [bool]$DryRun = $false
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

    function Resolve-RepoRelativePath {
        param(
            [string]$BasePath,
            [string]$CandidatePath
        )

        $text = [string]$CandidatePath
        if ([string]::IsNullOrWhiteSpace($text)) {
            return $null
        }

        if (-not [System.IO.Path]::IsPathRooted($text)) {
            return $text.Replace('\', '/')
        }

        try {
            $baseFullPath = [System.IO.Path]::GetFullPath($BasePath).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
            $candidateFullPath = [System.IO.Path]::GetFullPath($text)
            $prefixWithSeparator = $baseFullPath + [System.IO.Path]::DirectorySeparatorChar
            if ($candidateFullPath.StartsWith($prefixWithSeparator, [System.StringComparison]::OrdinalIgnoreCase)) {
                return $candidateFullPath.Substring($prefixWithSeparator.Length).Replace('\', '/')
            }
            if ($candidateFullPath.Equals($baseFullPath, [System.StringComparison]::OrdinalIgnoreCase)) {
                return '.'
            }

            $repoLeaf = Split-Path -Leaf $baseFullPath
            if (-not [string]::IsNullOrWhiteSpace($repoLeaf)) {
                $marker = [System.IO.Path]::DirectorySeparatorChar + $repoLeaf + [System.IO.Path]::DirectorySeparatorChar
                $markerIndex = $candidateFullPath.LastIndexOf($marker, [System.StringComparison]::OrdinalIgnoreCase)
                if ($markerIndex -ge 0) {
                    return $candidateFullPath.Substring($markerIndex + $marker.Length).Replace('\', '/')
                }
            }

            return $text.Replace('\', '/')
        }
        catch {
            return $text.Replace('\', '/')
        }
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

        if ([string]::IsNullOrWhiteSpace($RepoPath)) {
            throw "RepoPath is empty before git operations"
        }

        if (-not (Test-Path (Join-Path $RepoPath ".git"))) {
            throw "RepoPath is not a valid git repo: $RepoPath"
        }

    Push-Location $RepoPath
    try {
        $result.branch = Get-CurrentBranch -RepoPath $RepoPath

        $stagedDeletePaths = @(& git diff --cached --name-only --diff-filter=D --relative)
        if ($LASTEXITCODE -ne 0) {
            throw "git diff --cached failed for $RepoPath with exit code $LASTEXITCODE"
        }
        foreach ($stagedDeletePath in $stagedDeletePaths) {
            if ([string]::IsNullOrWhiteSpace($stagedDeletePath)) {
                continue
            }
            & git restore --staged -- $stagedDeletePath
            if ($LASTEXITCODE -ne 0) {
                throw "git restore --staged failed for $RepoPath path $stagedDeletePath with exit code $LASTEXITCODE"
            }
        }

        $appendOnlyChangePaths = @()
        $appendOnlyChangePaths += @(& git diff --name-only --diff-filter=ACMRTUXB --relative)
        if ($LASTEXITCODE -ne 0) {
            throw "git diff failed for $RepoPath with exit code $LASTEXITCODE"
        }
        $appendOnlyChangePaths += @(& git ls-files --others --exclude-standard)
        if ($LASTEXITCODE -ne 0) {
            throw "git ls-files failed for $RepoPath with exit code $LASTEXITCODE"
        }
        foreach ($relativePath in @($appendOnlyChangePaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object -Unique)) {
            $normalizedRelativePath = ([string]$relativePath).Trim().Replace('\\', '/')
            & git add -A -f -- $normalizedRelativePath
            if ($LASTEXITCODE -ne 0) {
                throw "git add failed for $RepoPath path $normalizedRelativePath with exit code $LASTEXITCODE"
            }
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
            $repoRelativePath = Resolve-RepoRelativePath -BasePath $RepoPath -CandidatePath $relativePath
            if (-not (Test-Path -LiteralPath (Join-Path $RepoPath $repoRelativePath))) {
                Write-Host ("    skipping missing forced artifact path: {0}" -f $repoRelativePath) -ForegroundColor DarkYellow
                continue
            }
            & git add -f -- $repoRelativePath
            if ($LASTEXITCODE -ne 0) {
                throw "git add -f failed for $RepoPath path $repoRelativePath with exit code $LASTEXITCODE"
            }
        }

        $stagedDeletePaths = @(& git diff --cached --name-only --diff-filter=D --relative)
        if ($LASTEXITCODE -ne 0) {
            throw "git diff --cached failed for $RepoPath with exit code $LASTEXITCODE"
        }
        if ($stagedDeletePaths.Count -gt 0) {
            $sampleDeletePaths = ($stagedDeletePaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 5) -join ', '
            throw ("Historical artifact deletion detected for {0}; refusing to publish delete paths: {1}" -f $RepoPath, $sampleDeletePaths)
        }

        # Only attempt commit when there are staged changes.
        
        if ([string]::IsNullOrWhiteSpace($RepoPath)) {
            throw "RepoPath is empty - cannot perform git operations"
        }

        & git diff --cached --quiet --exit-code
        $stagedDiffExitCode = $LASTEXITCODE
        if ($stagedDiffExitCode -eq 0) {
            $result.status = 'no_changes'
            return [pscustomobject]$result
        }
        if ($stagedDiffExitCode -ne 1) {
            throw "git diff --cached --quiet failed for $RepoPath with exit code $stagedDiffExitCode"
        }

        & git config user.name "github-actions[bot]"
        & git config user.email "github-actions[bot]@users.noreply.github.com"

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

    # Ensure remote name exists
        if ([string]::IsNullOrWhiteSpace($RemoteName)) {
            $RemoteName = "origin"
        }

        # Ensure branch exists
        if ([string]::IsNullOrWhiteSpace($result.branch)) {
            throw "Branch name is empty - cannot push"
        }

        Write-Host "Pushing to $RemoteName $($result.branch)"

        & git push $RemoteName $result.branch
        if ($LASTEXITCODE -ne 0) {
            Write-Host "⚠️ Push rejected, attempting pull + rebase..." -ForegroundColor Yellow

            
            & git pull --rebase $RemoteName $result.branch
            & git push $RemoteName $result.branch


            if ($LASTEXITCODE -ne 0) {
                throw "git push failed after retry"
            }
        }
 

        $result.status = 'pushed'
        return [pscustomobject]$result
    }
    finally {
        Pop-Location
    }
}

function Get-IntelligencePublishArtifactPaths {
    param(
        [string]$RepoPath,
        [string]$DateValue,
        [bool]$SkipMLB,
        [bool]$SkipNBA,
        [bool]$SkipNHL,
        [bool]$SkipWNBA,
        [bool]$SkipNFL,
        [bool]$SkipNCAAF,
        [bool]$SkipNCAAB
    )

    if ([string]::IsNullOrWhiteSpace($RepoPath) -or [string]::IsNullOrWhiteSpace($DateValue)) {
        return @()
    }

    $pythonExe = Resolve-Python $RepoPath
    $tempScriptPath = Join-Path $RepoPath '.tmp_unified_daily_update_intelligence_publish_paths.py'
    $scriptContent = @'

import json
import sys
from pathlib import Path

from syndicate.app import create_app
from syndicate.features.intelligence import _advanced_input_specs_for_sport
from syndicate.features.intelligence import _status_overview_rows


def _relative_repo_path(path: Path, repo_root: Path) -> str | None:
    try:
        resolved = path.resolve()
    except Exception:
        resolved = path
    try:
        relative = resolved.relative_to(repo_root.resolve())
    except Exception:
        return None
    return str(relative).replace("\\", "/")


def main() -> int:
    selected_date = str(sys.argv[1] or "").strip()
    skipped = {str(arg or "").strip().lower() for arg in sys.argv[2:] if str(arg or "").strip()}
    repo_root = Path.cwd().resolve()
    app = create_app()
    rows: list[str] = []
    with app.app_context():
        overview = _status_overview_rows(selected_date=selected_date)
        for sport in overview:
            slug = str(sport.get("slug") or "").strip().lower()
            if not slug or slug in skipped:
                continue
            for spec in _advanced_input_specs_for_sport(sport):
                path = spec.get("path")
                if not isinstance(path, Path):
                    continue
                try:
                    if not path.exists():
                        continue
                except OSError:
                    continue
                relative = _relative_repo_path(path, repo_root)
                if relative:
                    rows.append(relative)
    for relative_path in [
        Path("reports/intelligence/board_snapshot.json"),
        Path("reports/intelligence/intelligence_state.json"),
        Path("reports/intelligence/intelligence_state_history.jsonl"),
        Path("reports/intelligence/status_response_cache.json"),
        Path("reports/intelligence/query_state_cache.json"),
        Path("reports/intelligence/query_response_cache.json"),
        Path("reports/intelligence/query_response_version.json"),
        Path("reports/intelligence/performance_summary.json"),
    ]:
        path = repo_root / relative_path
        if not path.exists():
            continue
        relative = _relative_repo_path(path, repo_root)
        if relative:
            rows.append(relative)
    print(json.dumps(sorted(set(rows))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'@
    Set-Content -Path $tempScriptPath -Value $scriptContent -Encoding UTF8

    $skippedSports = New-Object System.Collections.Generic.List[string]
    if ($SkipMLB) { $skippedSports.Add('mlb') | Out-Null }
    if ($SkipNBA) { $skippedSports.Add('nba') | Out-Null }
    if ($SkipNHL) { $skippedSports.Add('nhl') | Out-Null }
    if ($SkipWNBA) { $skippedSports.Add('wnba') | Out-Null }
    if ($SkipNFL) { $skippedSports.Add('nfl') | Out-Null }
    if ($SkipNCAAF) { $skippedSports.Add('ncaaf') | Out-Null }
    if ($SkipNCAAB) { $skippedSports.Add('ncaab') | Out-Null }

    Push-Location $RepoPath
    try {
        $rawOutput = & $pythonExe $tempScriptPath $DateValue @($skippedSports)
        if ($LASTEXITCODE -ne 0) {
            throw "intelligence publish path builder exited with code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
        Remove-Item -Path $tempScriptPath -Force -ErrorAction SilentlyContinue
    }

    try {
        $paths = @((($rawOutput | Out-String) | ConvertFrom-Json -ErrorAction Stop))
    }
    catch {
        throw 'Unable to parse intelligence publish paths payload'
    }

    return @($paths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
}

function Assert-IntelligenceSportReady {
    param(
        [string]$Sport,
        [string]$DateValue,
        [string]$RepoRoot,
        [bool]$RequirePublishTrackedInputs = $true
    )

    if ([string]::IsNullOrWhiteSpace($Sport) -or [string]::IsNullOrWhiteSpace($DateValue) -or [string]::IsNullOrWhiteSpace($RepoRoot)) {
        return
    }

    function New-IntelligenceReadinessFallback {
        param(
            [string]$SportName,
            [string]$Status,
            [string]$Detail
        )

        return [pscustomobject]@{
            sport = $SportName
            state = 'unavailable'
            active_today = $false
            missing_inputs = @()
            publish_missing_inputs = @()
            ok = $false
            status = $Status
            detail = $Detail
        }
    }

    $pythonExe = Resolve-Python $RepoRoot
    $script = @'
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

sport_slug = str(sys.argv[1] or "").strip().lower()
selected_date = str(sys.argv[2] or "").strip()
with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
    from syndicate.app import create_app
    from syndicate.features.intelligence import build_intelligence_status

    app = create_app()
    with app.app_context():
        payload = build_intelligence_status(selected_date=selected_date, force_refresh=True)

row = {}
for sport in payload.get("sports") or []:
    if not isinstance(sport, dict):
        continue
    if str(sport.get("slug") or "").strip().lower() == sport_slug:
        row = sport
        break

gate = row.get("advanced_gate") if isinstance(row.get("advanced_gate"), dict) else {}
missing = [str(item.get("label") or "input").strip() for item in (gate.get("missing_inputs") or []) if isinstance(item, dict)]
unpublished = [str(item.get("label") or "input").strip() for item in (gate.get("publish_missing_inputs") or []) if isinstance(item, dict)]
state = str((row.get("readiness_gate") or {}).get("state") or "").strip().lower()
result = {
    "sport": sport_slug,
    "state": state,
    "active_today": bool(row.get("active_today")),
    "missing_inputs": missing,
    "publish_missing_inputs": unpublished,
    "ok": not missing and not unpublished,
}
print(json.dumps(result))
'@

    $tempScriptPath = Join-Path $RepoRoot (
        '.tmp_syndicate_intelligence_status_{0}_{1}.py' -f ([System.Guid]::NewGuid().ToString('N')), $PID
    )
    Set-Content -Path $tempScriptPath -Value $script -Encoding utf8

    Push-Location $RepoRoot
    try {
        $rawOutput = & $pythonExe $tempScriptPath $Sport $DateValue
        if ($LASTEXITCODE -ne 0) {
            Write-Warning ("Intelligence readiness audit unavailable for {0}: builder exited with code {1}" -f $Sport, $LASTEXITCODE)
            return
        }
    }
    finally {
        Pop-Location
        Remove-Item -Path $tempScriptPath -Force -ErrorAction SilentlyContinue
    }

    $statusText = ((($rawOutput | Out-String) -replace "^\uFEFF", "").Trim())
    if ([string]::IsNullOrWhiteSpace($statusText)) {
        Write-Warning ("Intelligence readiness audit unavailable for {0}: empty status payload" -f $Sport)
        return
    }

    $audit = $null
    try {
        $audit = $statusText | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        $jsonMatches = [regex]::Matches($statusText, '(?s)(\{.*\}|\[.*\])')
        foreach ($match in @($jsonMatches)) {
            try {
                $audit = $match.Groups[1].Value | ConvertFrom-Json -ErrorAction Stop
                break
            }
            catch {
            }
        }
        if (-not $audit) {
            Write-Warning ("Intelligence readiness audit unavailable for {0}: unable to parse status payload" -f $Sport)
            return
        }
    }

    if (-not ($audit -is [psobject]) -and -not ($audit -is [hashtable])) {
        Write-Warning ("Intelligence readiness audit unavailable for {0}: unexpected status payload type" -f $Sport)
        return
    }

    $missingLabels = @($audit.missing_inputs)
    if ($RequirePublishTrackedInputs) {
        $missingLabels += @($audit.publish_missing_inputs)
    }

    if ($missingLabels.Count -gt 0) {
        $detail = ($missingLabels | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join ', '
        if ([string]::IsNullOrWhiteSpace($detail)) {
            $detail = 'unknown intelligence readiness mismatch'
        }
        
        $inCI = $env:GITHUB_ACTIONS -eq "true"

        if ($inCI) {
            Write-Host "Intelligence readiness audit skipped in CI for ${Sport}: $detail" -ForegroundColor Yellow
            return
        }
        else {
            throw "Intelligence readiness audit failed for ${Sport}: $detail"
        }
    }
}

$sourceSteps = @()
$publishRepos = @()
$preferLocalMirrorArtifactsForGate = $false
$skipGitPushMode = $PSBoundParameters.ContainsKey('SkipGitPush') -and [bool]$SkipGitPush
$resolveForcedPublishArtifactPaths = {
    if ($skipGitPushMode) {
        return @()
    }
    @(
        Get-ForcedPublishArtifactPaths -RepoPath $repoRoot -DateValue $Date -SkipGitPush $skipGitPushMode -SkipMLB ([bool]$SkipMLB) -SkipNBA ([bool]$SkipNBA) -SkipNHL ([bool]$SkipNHL) -SkipWNBA ([bool]$SkipWNBA) -SkipNFL ([bool]$SkipNFL) -SkipNCAAF ([bool]$SkipNCAAF) -SkipNCAAB ([bool]$SkipNCAAB)
        Get-IntelligencePublishArtifactPaths -RepoPath $repoRoot -DateValue $Date -SkipMLB ([bool]$SkipMLB) -SkipNBA ([bool]$SkipNBA) -SkipNHL ([bool]$SkipNHL) -SkipWNBA ([bool]$SkipWNBA) -SkipNFL ([bool]$SkipNFL) -SkipNCAAF ([bool]$SkipNCAAF) -SkipNCAAB ([bool]$SkipNCAAB)
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
}
$sharedOddsApiKey = Get-ProcessEnvValue -Names @('ODDS_API_KEY', 'ODDSAPI_KEY', 'THEODDS_API_KEY', 'THEODDSAPI_KEY', 'NCAAB_THEODDS_API_KEY')
$ncaabOddsApiKey = Get-ProcessEnvValue -Names @('NCAAB_THEODDS_API_KEY', 'THEODDSAPI_KEY', 'THEODDS_API_KEY')

if (Test-SportEnabled 'MLB') {
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
            '--overwrite', 'on'
        )
        WorkingDirectory = $repoRoot
        EnvironmentOverrides = $mlbEnvOverrides
        RuntimePolicy = $runtimePolicy.MLB
    }
}
if (Test-SportEnabled 'NBA') {
    $nbaVendoredRoot = Resolve-VendoredRepoPath -RelativePath 'vendor\nba_betting_repo'
    $nbaVendoredApp = if ($nbaVendoredRoot) { Join-Path $nbaVendoredRoot 'app.py' } else { $null }
    if (-not ($nbaVendoredApp -and (Test-Path $nbaVendoredApp))) {
        throw "NBA self-contained refresh is unavailable because vendor\\nba_betting_repo\\app.py was not found. The fallback NBA Syndicate props refresh still requires a source-root for fresh runs and is not a self-contained replacement."
    }

    $nbaScheduleCheck = Get-BasketballScheduledGamesCheck -Sport 'nba' -DateValue $Date
    if ($nbaScheduleCheck.known -and [int]$nbaScheduleCheck.count -eq 0) {
        Write-Host ("NBA vendored daily update skipped: no scheduled games for {0} ({1})" -f $Date, $nbaScheduleCheck.source) -ForegroundColor DarkGray
    }
    else {

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
            '--artifact-root', 'data\nba_source\source_artifacts',
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
    $sourceSteps += [pscustomobject]@{
        Sport = 'nba'
        Name = 'NBA source mirror refresh'
        Workflow = 'syndicate_mirror'
        Command = @(
            'powershell.exe',
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-File', 'scripts\refresh_nba_source_mirror.ps1',
            '-Date', $Date
        )
        WorkingDirectory = $repoRoot
        EnvironmentOverrides = @{}
        RuntimePolicy = $runtimePolicy.NBA
    }
    }
}
if (Test-SportEnabled 'WNBA') {
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
        REFRESH_PLAYER_LOGS_FETCH_ON_MISS = '1'
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
            '--artifact-root', 'data\wnba_source\source_artifacts',
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
    $sourceSteps += [pscustomobject]@{
        Sport = 'wnba'
        Name = 'WNBA source mirror refresh'
        Workflow = 'syndicate_mirror'
        Command = @(
            'powershell.exe',
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-File', 'scripts\refresh_wnba_source_mirror.ps1',
            '-Date', $Date
        )
        WorkingDirectory = $repoRoot
        EnvironmentOverrides = @{}
        RuntimePolicy = $runtimePolicy.WNBA
    }
}
if (Test-SportEnabled 'NHL') {
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
if (Test-SportEnabled 'NFL') {
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
if (Test-SportEnabled 'NCAAF') {
    $ncaafEnvOverrides = @{}
    if (-not [string]::IsNullOrWhiteSpace($sharedOddsApiKey)) {
        $ncaafEnvOverrides.ODDS_API_KEY = $sharedOddsApiKey
    }
    $ncaafSourceRoot = [Environment]::GetEnvironmentVariable('SYNDICATE_SOURCE_ROOT_NCAAF')
    if ([string]::IsNullOrWhiteSpace($ncaafSourceRoot)) {
        $ncaafSourceRoot = Resolve-WorkspaceRepoPath 'NCAAFCompare'
    }
    if ([string]::IsNullOrWhiteSpace($ncaafSourceRoot) -or (-not (Test-Path $ncaafSourceRoot))) {
        Write-Host 'NCAAF local odds refresh skipped: SYNDICATE_SOURCE_ROOT_NCAAF is not set and the NCAAFCompare workspace repo is not available.' -ForegroundColor Yellow
    }
    else {
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
}
if (Test-SportEnabled 'NCAAB') {
    $ncaabRawOutputsRoot = Join-Path $repoRoot 'data\ncaab_source\raw_outputs'
    $ncaabApiKey = $ncaabOddsApiKey
    if (-not [string]::IsNullOrWhiteSpace($ncaabApiKey)) {
        $sourceSteps += [pscustomobject]@{
            Sport = 'ncaab'
            Workflow = 'syndicate_refresh'
            Name = 'NCAAB Syndicate odds refresh'
            Command = @(
                (Resolve-Python $repoRoot),
                'scripts\refresh_ncaab_odds_history.py',
                '--date', $Date,
                '--out-dir', (Join-Path 'data\ncaab_source\raw_outputs\by_date' $Date)
            )
            WorkingDirectory = $repoRoot
            EnvironmentOverrides = @{ NCAAB_THEODDS_API_KEY = $ncaabApiKey }
            RuntimePolicy = @{}
        }
    }
    elseif (-not (Test-Path $ncaabRawOutputsRoot)) {
        throw "NCAAB raw outputs not found at $ncaabRawOutputsRoot and no NCAAB/TheOddsAPI key is available for a local refresh."
    }

    $sourceSteps += [pscustomobject]@{
        Sport = 'ncaab'
        Workflow = 'syndicate_mirror'
        Name = 'NCAAB source mirror export'
        Command = @(
            (Resolve-Python $repoRoot),
            'scripts\export_ncaab_source_mirror.py',
            'data\ncaab_source\api',
            $Date,
            '--raw-root', 'data\ncaab_source\raw_outputs'
        )
        WorkingDirectory = $repoRoot
        EnvironmentOverrides = @{}
        RuntimePolicy = @{}
    }
}

$publishRepos += [pscustomobject]@{ Name = 'Syndicate'; RepoPath = $repoRoot; CommitMessage = "$CommitMessagePrefix $Date (Syndicate mirror + gate)" }

$simExecutionDecision = Get-SimExecutionDecision -RepoRoot $repoRoot -DateValue $Date -LatestManifestPath $latestManifestPath -LatestCheckpointPath $latestCheckpointPath -SourceSteps $sourceSteps -SkipSourceUpdates ([bool]$SkipSourceUpdates) -ForceRebuildToday ([bool]$ForceRebuildToday)
$latestManifest = $null
$latestEventSimExecutionPlan = @()
$latestCheckpoint = $null
if (Test-Path -LiteralPath $latestManifestPath) {
    try {
        $latestManifest = Get-Content -Path $latestManifestPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        $latestEventSimExecutionPlan = @($latestManifest.eventSimExecution)
    }
    catch {
        $latestManifest = $null
        $latestEventSimExecutionPlan = @()
    }
}

if (Test-Path -LiteralPath $latestCheckpointPath) {
    try {
        $latestCheckpoint = Get-Content -Path $latestCheckpointPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        $latestCheckpoint = $null
    }
}

$oddsHistoryTriggerPlan = @(
    $sourceSteps | ForEach-Object {
        Get-OddsHistoryTriggerDecision -RepoRoot $repoRoot -DateValue $Date -Sport $_.Sport -Workflow $_.Workflow
    }
)

$runManifest = [ordered]@{
    date = $Date
    generatedAt = (Get-Date).ToString('o')
    lastUpdatedAt = $null
    completedAt = $null
    runMode = if ($DryRun) { 'dry_run' } else { 'standard' }
    overallStatus = if ($DryRun) { 'dry_run' } else { 'started' }
    error = $null
    runDir = $runDir
    latestDir = $latestDir
    runtimePolicy = $runtimePolicy
    runPlan = [ordered]@{
        simExecution = $simExecutionDecision
        eventSimExecution = @()
        artifactUpdates = @()
        policyPerformance = @()
        sourceUpdates = [bool](-not $SkipSourceUpdates)
        refreshGate = [bool](-not $SkipRefreshGate)
        artifactGeneration = $true
        manifestGeneration = $true
        publish = [bool](-not $SkipGitPush)
        refreshOdds = [bool]$RefreshOdds
        oddsPhase = $OddsPhase
        oddsSports = $OddsSports
        oddsRegions = $OddsRegions
        oddsHistoryTriggerPlan = @($oddsHistoryTriggerPlan)
    }
    publishParity = New-PublishParitySummary -DateValue $Date -SkipGitPush ([bool]$SkipGitPush) -ForcedPublishArtifactPaths $forcedPublishArtifactPaths -IntelligencePublishArtifactPaths $intelligencePublishArtifactPaths
    runProvenance = [ordered]@{
        sourceStepCount = $sourceSteps.Count
        sourceSteps = @($sourceSteps | ForEach-Object { [ordered]@{ sport = $_.Sport; workflow = $_.Workflow; name = $_.Name } })
        latestManifestLoaded = [bool]($null -ne $latestManifest)
        latestEventSimExecutionPlanCount = $latestEventSimExecutionPlan.Count
        latestArtifactUpdateCount = @($latestManifest.artifactUpdates).Count
        oddsHistoryTriggerPlanCount = @($oddsHistoryTriggerPlan).Count
        simExecutionDecision = $simExecutionDecision
    }
    replayContext = [ordered]@{
        latestCheckpointLoaded = [bool]($null -ne $latestCheckpoint)
        latestCheckpointPath = $latestCheckpointPath
        latestCheckpointStage = if ($null -ne $latestCheckpoint) { [string]$latestCheckpoint.currentStage } else { $null }
        latestCheckpointFailedStage = if ($null -ne $latestCheckpoint) { [string]$latestCheckpoint.failedStage } else { $null }
        latestCheckpointCompletedStageCount = if ($null -ne $latestCheckpoint) { @($latestCheckpoint.completedStages).Count } else { 0 }
        latestCheckpointCompletedStages = if ($null -ne $latestCheckpoint) { @($latestCheckpoint.completedStages) } else { @() }
        resumeEligible = [bool]($null -ne $latestCheckpoint -and -not [string]::IsNullOrWhiteSpace([string]$latestCheckpoint.currentStage) -and [string]$latestCheckpoint.currentStage -ne 'queued' -and [string]$latestCheckpoint.currentStage -ne 'completed')
        resumedFromCheckpoint = [bool]($null -ne $latestCheckpoint -and $null -eq $latestManifest)
        forceRebuildToday = [bool]$ForceRebuildToday
    }
    runState = [ordered]@{
        currentStage = 'queued'
        completedStages = @()
        failedStage = $null
        lastUpdatedAt = $null
        simulationContractPath = $null
        simulationContractRunPath = $null
        simulationContractSportCount = 0
        simulationContractAdvancedBySport = $null
    }
    eventSimExecution = @()
    artifactUpdates = @()
    policyPerformance = @()
    sourceSteps = @($sourceSteps | ForEach-Object { [ordered]@{ sport = $_.Sport; workflow = $_.Workflow; name = $_.Name; workingDirectory = $_.WorkingDirectory; environmentOverrides = $_.EnvironmentOverrides; runtimePolicy = $_.RuntimePolicy; command = $_.Command } })
    stageDecisions = @(
        @($sourceSteps | ForEach-Object { [ordered]@{ stage = 'source_update'; sport = $_.Sport; workflow = $_.Workflow; name = $_.Name; decision = 'planned'; status = if ($DryRun) { 'dry_run' } else { 'pending' } } })
        [ordered]@{ stage = 'sim_execution'; decision = if ($simExecutionDecision -eq $false) { 'skipped' } elseif ($simExecutionDecision -eq $true) { 'planned' } else { 'planned' }; status = if ($simExecutionDecision -eq $false) { 'skipped' } else { if ($DryRun) { 'dry_run' } else { 'pending' } } }
        [ordered]@{ stage = 'event_sim_execution'; decision = if ($simExecutionDecision -eq $false) { 'skipped' } else { 'planned' }; status = if ($simExecutionDecision -eq $false) { 'skipped' } else { if ($DryRun) { 'dry_run' } else { 'pending' } } }
        [ordered]@{ stage = 'refresh_gate'; decision = if ($SkipRefreshGate) { 'skipped' } else { 'planned' }; status = if ($SkipRefreshGate) { 'skipped' } else { if ($DryRun) { 'dry_run' } else { 'pending' } } }
        [ordered]@{ stage = 'artifact_generation'; decision = if ($SkipGitPush) { 'skipped' } else { 'planned' }; status = if ($SkipGitPush) { 'skipped' } else { if ($DryRun) { 'dry_run' } else { 'pending' } } }
        [ordered]@{ stage = 'manifest_generation'; decision = 'planned'; status = if ($DryRun) { 'dry_run' } else { 'pending' } }
        [ordered]@{ stage = 'git_publish'; decision = if ($SkipGitPush) { 'skipped' } else { 'planned' }; status = if ($SkipGitPush) { 'skipped' } else { if ($DryRun) { 'dry_run' } else { 'pending' } } }
    )
    simTriggerPlan = @(
        $oddsHistoryTriggerPlan | ForEach-Object {
            if ($null -eq $_) {
                return [ordered]@{ trigger = 'planned'; status = if ($DryRun) { 'dry_run' } else { 'pending' }; reason = 'simulation compute is foundational and deferred until source-stage completion' }
            }

            [ordered]@{
                sport = $_.sport
                workflow = $_.workflow
                trigger = $_.trigger
                status = if ($DryRun) { 'dry_run' } else { 'pending' }
                reason = $_.reason
                hasLineMovement = $_.hasLineMovement
                maxDeltaDetected = $_.maxDeltaDetected
                lastOddsUpdateTimestamp = $_.lastOddsUpdateTimestamp
                priorityScoring = $_.priorityScoring
                runSimulation = $_.runSimulation
                oddsHistoryPath = $_.oddsHistoryPath
            }
        }
    )
    statusArtifact = [ordered]@{
        format = 'json'
        scope = 'daily_update'
        runManifestPath = $runManifestPath
        latestManifestPath = $latestManifestPath
        runCheckpointPath = $runCheckpointPath
        latestCheckpointPath = $latestCheckpointPath
        state = [ordered]@{
            runMode = if ($DryRun) { 'dry_run' } else { 'standard' }
            overallStatus = if ($DryRun) { 'dry_run' } else { 'started' }
            currentStage = 'queued'
            completedStages = @()
            failedStage = $null
            policyPerformance = @()
            replayContext = $null
            publishParity = New-PublishParitySummary -DateValue $Date -SkipGitPush ([bool]$SkipGitPush) -ForcedPublishArtifactPaths $forcedPublishArtifactPaths -IntelligencePublishArtifactPaths $intelligencePublishArtifactPaths
        }
    }
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
        refreshOdds = [bool]$RefreshOdds
        oddsPhase = $OddsPhase
        oddsSports = $OddsSports
        oddsRegions = $OddsRegions
        manifestPath = (Join-Path $runDir 'migration\refresh_status_manifest.json')
        runSummaryPath = (Join-Path $runDir 'migration\refresh_and_gate_run.json')
    }
    pushResults = @()
}

if ($null -ne $latestManifest) {
    $runManifest.eventSimExecution = @($latestManifest.eventSimExecution)
    $runManifest.runPlan.eventSimExecution = @($latestManifest.eventSimExecution)
    $runManifest.artifactUpdates = @($latestManifest.artifactUpdates)
    $runManifest.runPlan.artifactUpdates = @($latestManifest.artifactUpdates)
}

Set-RunReplayContext -Manifest $runManifest -ReplayContext $runManifest.replayContext

Sync-RunManifestPolicyPerformance -Manifest $runManifest

$sourceUpdateAlreadyCompleted = [bool](
    $runManifest.replayContext.latestCheckpointLoaded -and
    @($runManifest.runState.completedStages) -contains 'source_update' -and
    [string]$runManifest.runState.currentStage -ne 'source_update'
)

$shouldRunManifestGeneration = Get-RunPlanDecisionValue -Plan $runManifest.runPlan -Key 'manifestGeneration' -Fallback $true
if ($shouldRunManifestGeneration) {
    Write-RunManifest -Manifest $runManifest
}

Push-Location $repoRoot
try {
    if ($SkipRefreshGate -and -not $SkipGitPush) {
        throw 'Cannot push git updates when -SkipRefreshGate is set. Run the gate or pass -SkipGitPush.'
    }

    $shouldRunArtifactGeneration = Get-RunPlanDecisionValue -Plan $runManifest.runPlan -Key 'artifactGeneration' -Fallback ([bool](-not $SkipGitPush))
    if ($shouldRunArtifactGeneration) {
        foreach ($repo in $publishRepos) {
            $result = Invoke-GitPublish -Name $repo.Name -RepoPath $repo.RepoPath -CommitMessage "$CommitMessagePrefix $Date (pre-source publish)" -RemoteName $GitRemote -ForceIncludePaths (& $resolveForcedPublishArtifactPaths) -DryRun ([bool]$DryRun)
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

    $shouldRunSimExecution = Get-RunPlanDecisionValue -Plan $runManifest.runPlan -Key 'simExecution' -Fallback ([bool](-not $SkipSourceUpdates))
    $simExecutionNoOpDecision = if ($ForceRebuildToday) { $null } else { Get-SimExecutionNoOpDecision -RepoRoot $repoRoot -DateValue $Date -LatestEventSimExecutionPlan $latestEventSimExecutionPlan }
    $artifactGenerationFallbackToFullPublish = $false
    if (-not $ForceRebuildToday -and $simExecutionNoOpDecision -eq $false) {
        Write-Host 'Sim stage no-op: all planned event fingerprints are unchanged; skipping simulation stage.' -ForegroundColor Yellow
        $shouldRunSimExecution = $false
        foreach ($stageDecision in @($runManifest.stageDecisions | Where-Object { [string]$_.stage -eq 'sim_execution' -or [string]$_.stage -eq 'event_sim_execution' })) {
            $stageDecision.decision = 'skipped'
            $stageDecision.status = if ($DryRun) { 'dry_run' } else { 'skipped' }
        }
    }
    $shouldRunSourceUpdate = [bool]((Get-RunPlanDecisionValue -Plan $runManifest.runPlan -Key 'sourceUpdates' -Fallback ([bool](-not $SkipSourceUpdates))) -and -not $sourceUpdateAlreadyCompleted)
    if ($shouldRunSourceUpdate) {
        Update-RunStateStage -Manifest $runManifest -Stage 'source_update' -Status 'started'
        for ($stepIndex = 0; $stepIndex -lt $sourceSteps.Count; $stepIndex++) {
            $step = $sourceSteps[$stepIndex]
            $sportKey = [string]$step.Sport
            $startedAt = (Get-Date).ToString('o')
            $isMlbVendoredStep = ($step.Sport -eq 'mlb' -and $step.Workflow -eq 'vendored_daily_update')
            $mlbDataRootForStep = $null
            if ($isMlbVendoredStep -and $step.EnvironmentOverrides -and $step.EnvironmentOverrides.ContainsKey('MLB_BETTING_DATA_ROOT')) {
                $mlbDataRootForStep = [string]$step.EnvironmentOverrides.MLB_BETTING_DATA_ROOT
            }
            $currentEventInputFingerprint = Get-EventInputFingerprint -RepoRoot $repoRoot -DateValue $Date -Sport $step.Sport -Workflow $step.Workflow
            $stepEventPlans = @(
                $latestEventSimExecutionPlan |
                    Where-Object { [string]$_.sport -eq [string]$step.Sport -and [string]$_.workflow -eq [string]$step.Workflow }
            )
            $stepEventDecisions = @()
            $stepShouldRunSim = $null
            if ($ForceRebuildToday -and $stepEventPlans.Count -gt 0) {
                $stepShouldRunSim = $true
                foreach ($eventPlan in $stepEventPlans) {
                    $eventStartTimeUtc = Get-EventSimExecutionStartTimeUtc -EventPlan $eventPlan
                    $currentTimeUtc = [DateTimeOffset]::UtcNow
                    $timeToStartMinutes = $null
                    if ($null -ne $currentTimeUtc -and $null -ne $eventStartTimeUtc) {
                        $timeToStartMinutes = [math]::Round(($eventStartTimeUtc - $currentTimeUtc).TotalMinutes, 2)
                    }

                    $stepEventDecisions += @([ordered]@{
                        sport = [string]$step.Sport
                        workflow = [string]$step.Workflow
                        eventKey = [string]$eventPlan.eventKey
                        artifactPath = [string]$eventPlan.artifactPath
                        inputFingerprint = [string](Get-EventInputFingerprint -RepoRoot $repoRoot -DateValue $Date -Sport $step.Sport -Workflow $step.Workflow)
                        previousInputFingerprint = [string]$eventPlan.inputFingerprint
                        eventStartTimeUtc = if ($null -ne $eventStartTimeUtc) { [string]$eventStartTimeUtc.UtcDateTime.ToString('o') } else { $null }
                        timeToStartMinutes = $timeToStartMinutes
                        policyId = 'policy:forced-rebuild'
                        policySource = 'rerun'
                        policySelectionMode = 'forced'
                        isExploratory = $false
                        policyKeyParameters = [ordered]@{ forceRebuildToday = $true }
                        forceWithinMinutes = [int]$EventSimForceWindowMinutes
                        decision = 'planned'
                        status = if ($DryRun) { 'dry_run' } else { 'pending' }
                    })
                }
            }
            elseif ($stepEventPlans.Count -gt 0) {
                $stepShouldRunSim = $false
                foreach ($eventPlan in $stepEventPlans) {
                    $previousInputFingerprint = [string]$eventPlan.inputFingerprint
                    $eventStartTimeUtc = Get-EventSimExecutionStartTimeUtc -EventPlan $eventPlan
                    $currentTimeUtc = [DateTimeOffset]::UtcNow
                    $timeToStartMinutes = $null
                    if ($null -ne $currentTimeUtc -and $null -ne $eventStartTimeUtc) {
                        $timeToStartMinutes = [math]::Round(($eventStartTimeUtc - $currentTimeUtc).TotalMinutes, 2)
                    }

                    $eventPolicyContext = [pscustomobject]@{
                        sport = [string]$step.Sport
                        market = [string]$step.Workflow
                        timeToStartMinutes = $timeToStartMinutes
                    }
                    $eventPolicy = Get-Policy -Context $eventPolicyContext -PolicyConfig $eventSimPolicyConfig -PolicyPerformance @($runManifest.policyPerformance)
                    $effectivePolicy = if ($null -ne $eventPolicy) { $eventPolicy } else { [ordered]@{ policyId = 'policy:default'; policySource = 'fallback'; keyParameters = [ordered]@{ forceWithinMinutes = [int]$EventSimForceWindowMinutes } } }
                    $effectiveForceWindowMinutes = if ($null -ne $effectivePolicy -and $null -ne $effectivePolicy.keyParameters -and $null -ne $effectivePolicy.keyParameters.forceWithinMinutes) { [int]$effectivePolicy.keyParameters.forceWithinMinutes } else { [int]$EventSimForceWindowMinutes }

                    $eventDecision = Get-EventSimExecutionDecision -CurrentFingerprint $currentEventInputFingerprint -PreviousFingerprint $previousInputFingerprint -Fallback $null -CurrentTimeUtc $currentTimeUtc -EventStartTimeUtc $eventStartTimeUtc -ArtifactPath [string]$eventPlan.artifactPath -ForceWithinMinutes $effectiveForceWindowMinutes
                    if ($null -eq $eventDecision) {
                        $stepShouldRunSim = $null
                        $stepEventDecisions = @()
                        break
                    }

                    if ($eventDecision) {
                        $stepShouldRunSim = $true
                        $stepEventDecisions += @([ordered]@{
                            sport = [string]$step.Sport
                            workflow = [string]$step.Workflow
                            eventKey = [string]$eventPlan.eventKey
                            artifactPath = [string]$eventPlan.artifactPath
                            inputFingerprint = [string]$currentEventInputFingerprint
                            previousInputFingerprint = $previousInputFingerprint
                            eventStartTimeUtc = if ($null -ne $eventStartTimeUtc) { [string]$eventStartTimeUtc.UtcDateTime.ToString('o') } else { $null }
                            timeToStartMinutes = $timeToStartMinutes
                            policyId = [string]$effectivePolicy.policyId
                            policySource = [string]$effectivePolicy.policySource
                            policySelectionMode = [string]$effectivePolicy.selectionMode
                            isExploratory = [bool]$effectivePolicy.isExploratory
                            policyKeyParameters = $effectivePolicy.keyParameters
                            forceWithinMinutes = [int]$effectiveForceWindowMinutes
                            decision = 'planned'
                            status = if ($DryRun) { 'dry_run' } else { 'pending' }
                        })
                    }
                }
            }

            if ($null -eq $stepShouldRunSim) {
                $stepShouldRunSim = $shouldRunSimExecution
            }
            $sportRun = [pscustomobject][ordered]@{
                sport = $step.Sport
                workflow = $step.Workflow
                name = $step.Name
                startedAt = $startedAt
                completedAt = $null
                status = if ($DryRun) { 'dry_run' } else { 'started' }
                error = $null
                workingDirectory = $step.WorkingDirectory
                environmentOverrides = $step.EnvironmentOverrides
                runtimePolicy = $step.RuntimePolicy
                command = $step.Command
                mirrorManifestPath = (Get-MirrorManifestPath -Sport $step.Sport -DateValue $Date)
                mirrorManifestExists = $false
            }
            $runManifest.sportRuns += @($sportRun)
            if ($shouldRunManifestGeneration) {
                Write-RunManifest -Manifest $runManifest
            }

            if ($stepEventDecisions.Count -gt 0) {
                Sync-RunManifestEventRecords -Manifest $runManifest -EventRecords $stepEventDecisions -ArtifactUpdateRecords @($stepEventDecisions | ForEach-Object {
                    [ordered]@{
                        sport = [string]$_.sport
                        workflow = [string]$_.workflow
                        eventKey = [string]$_.eventKey
                        artifactPath = [string]$_.artifactPath
                        inputFingerprint = [string]$_.inputFingerprint
                        previousInputFingerprint = [string]$_.previousInputFingerprint
                        policyId = [string]$_.policyId
                        policySource = [string]$_.policySource
                        policyKeyParameters = $_.policyKeyParameters
                        decision = [string]$_.decision
                        status = [string]$_.status
                    }
                })
                Sync-RunManifestPolicyPerformance -Manifest $runManifest
                if ($shouldRunManifestGeneration) {
                    Write-RunManifest -Manifest $runManifest
                }
            }

            if (($stepEventPlans.Count -eq 0) -and ($null -eq $latestManifest) -and -not [string]::IsNullOrWhiteSpace([string]$currentEventInputFingerprint) -and $stepShouldRunSim) {
                $artifactGenerationFallbackToFullPublish = $true
            }

            if (-not $stepShouldRunSim) {
                $sportRun.status = 'skipped'
                $sportRun.completedAt = (Get-Date).ToString('o')
                if ($shouldRunManifestGeneration) {
                    Write-RunManifest -Manifest $runManifest
                }
                continue
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
                    Set-RunFailureState -Manifest $runManifest -Stage 'source_update' -Message $_.Exception.Message
                    if ($shouldRunManifestGeneration) {
                        Write-RunManifest -Manifest $runManifest
                    }
                    throw
                }
            }
            $sportRun.status = if ($DryRun) { 'dry_run' } else { 'ok' }
            $sportRun.completedAt = (Get-Date).ToString('o')
            if ($shouldRunManifestGeneration) {
                Write-RunManifest -Manifest $runManifest
            }


            if (($stepEventPlans.Count -eq 0) -and ($null -eq $latestManifest) -and $stepShouldRunSim) {
                $stepEventArtifactPaths = @()
                if ($step.Sport -eq 'mlb' -and $step.Workflow -eq 'vendored_daily_update') {
                    $stepEventArtifactPaths = @(Get-SimEventArtifactPaths -RepoRoot $repoRoot -DateValue $Date -Sport $step.Sport -Workflow $step.Workflow)
                }
                elseif ($step.Workflow -eq 'vendored_daily_update' -and ($step.Sport -eq 'nba' -or $step.Sport -eq 'wnba' -or $step.Sport -eq 'nhl')) {
                    $stepEventArtifactPaths = @(Get-SimEventArtifactPaths -RepoRoot $repoRoot -DateValue $Date -Sport $step.Sport -Workflow $step.Workflow)
                }

                $fullEventRecords = @()
                foreach ($artifactPath in @($stepEventArtifactPaths | Select-Object -Unique)) {
                    $eventKey = [IO.Path]::GetFileNameWithoutExtension($artifactPath)
                    $fullEventRecords += @([ordered]@{
                        sport = [string]$step.Sport
                        workflow = [string]$step.Workflow
                        eventKey = $eventKey
                        artifactPath = $artifactPath
                        candidateArtifactPaths = @($artifactPath)
                        inputFingerprint = [string]$currentEventInputFingerprint
                        decision = 'planned'
                        status = if ($DryRun) { 'dry_run' } else { 'pending' }
                    })
                }

                if ($fullEventRecords.Count -gt 0) {
                    Sync-RunManifestEventRecords -Manifest $runManifest -EventRecords $fullEventRecords -ArtifactUpdateRecords $fullEventRecords
                }
            }

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
                if ($SkipGitPush) {
                    Assert-IntelligenceSportReady -Sport $step.Sport -DateValue $Date -RepoRoot $repoRoot -RequirePublishTrackedInputs $false
                }
            }

            if ($shouldRunArtifactGeneration) {
                if ($artifactGenerationFallbackToFullPublish) {
                    foreach ($repo in $publishRepos) {
                        $result = Invoke-GitPublish -Name $repo.Name -RepoPath $repo.RepoPath -CommitMessage "$CommitMessagePrefix $Date [$($step.Name)]" -RemoteName $GitRemote -ForceIncludePaths (& $resolveForcedPublishArtifactPaths) -DryRun ([bool]$DryRun)
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

                    if (-not $DryRun -and -not $hasLaterStepForSport) {
                        Assert-IntelligenceSportReady -Sport $step.Sport -DateValue $Date -RepoRoot $repoRoot -RequirePublishTrackedInputs $true
                    }
                }
            }
        }

        Update-RunStateStage -Manifest $runManifest -Stage 'source_update' -Status 'completed'
    }
    elseif ($sourceUpdateAlreadyCompleted) {
        Write-Host 'Replay checkpoint: source_update already completed; continuing at the next stage.' -ForegroundColor Yellow
    }

    Update-RunStateStage -Manifest $runManifest -Stage 'refresh_gate' -Status 'started'
    $shouldRunRefreshGate = Get-RunPlanDecisionValue -Plan $runManifest.runPlan -Key 'refreshGate' -Fallback ([bool](-not $SkipRefreshGate))
    if ($shouldRunRefreshGate) {
        $refreshArgs = @(
            'powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'refresh_and_gate.ps1'),
            '-Date', $Date,
            '-ArtifactsDir', (Join-Path $runDir 'migration')
        )
        if ($BaseUrl) { $refreshArgs += @('-BaseUrl', $BaseUrl) }
        if ($Json) { $refreshArgs += '-Json' }
        if ($RefreshOdds) { $refreshArgs += '-RefreshOdds' }
        if ($OddsPhase) { $refreshArgs += @('-OddsPhase', $OddsPhase) }
        if ($OddsSports) { $refreshArgs += @('-OddsSports', $OddsSports) }
        if ($OddsRegions) { $refreshArgs += @('-OddsRegions', $OddsRegions) }
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
        if ($shouldRunManifestGeneration) {
            Write-RunManifest -Manifest $runManifest
        }
    }
    else {
        $runManifest.refreshGate.status = 'skipped'
        if ($shouldRunManifestGeneration) {
            Write-RunManifest -Manifest $runManifest
        }
    }

    Update-RunStateStage -Manifest $runManifest -Stage 'refresh_gate' -Status 'completed'

    foreach ($sportRun in @($runManifest.sportRuns)) {
        $mirrorManifestPath = [string]$sportRun.mirrorManifestPath
        if (-not [string]::IsNullOrWhiteSpace($mirrorManifestPath) -and (Test-Path $mirrorManifestPath)) {
            $sportRun | Add-Member -NotePropertyName mirrorManifestExists -NotePropertyValue $true -Force
        }
        else {
            $sportRun | Add-Member -NotePropertyName mirrorManifestExists -NotePropertyValue $false -Force
        }
    }

    if ($shouldRunArtifactGeneration) {
        $artifactUpdatePaths = @($runManifest.artifactUpdates | ForEach-Object { [string]$_.artifactPath } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
        if ($DryRun) {
            Write-Host 'Artifact stage dry-run: skipping artifact publish.' -ForegroundColor Yellow
            foreach ($stageDecision in @($runManifest.stageDecisions | Where-Object { [string]$_.stage -eq 'artifact_generation' })) {
                $stageDecision.decision = 'skipped'
                $stageDecision.status = 'dry_run'
            }
        }
        elseif ($artifactGenerationFallbackToFullPublish) {
            foreach ($repo in $publishRepos) {
                $result = Invoke-GitPublish -Name $repo.Name -RepoPath $repo.RepoPath -CommitMessage $repo.CommitMessage -RemoteName $GitRemote -ForceIncludePaths (& $resolveForcedPublishArtifactPaths) -DryRun ([bool]$DryRun)
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
        elseif ($artifactUpdatePaths.Count -gt 0) {
            Write-Host ("Artifact stage incremental: publishing {0} updated event artifact(s)." -f $artifactUpdatePaths.Count) -ForegroundColor Yellow
            foreach ($repo in $publishRepos) {
                $result = Invoke-GitPublish -Name $repo.Name -RepoPath $repo.RepoPath -CommitMessage $repo.CommitMessage -RemoteName $GitRemote -ForceIncludePaths $artifactUpdatePaths -DryRun ([bool]$DryRun)
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
        else {
            Write-Host 'Artifact stage no-op: no event-level artifact updates were scheduled; skipping artifact publish.' -ForegroundColor Yellow
            foreach ($stageDecision in @($runManifest.stageDecisions | Where-Object { [string]$_.stage -eq 'artifact_generation' })) {
                $stageDecision.decision = 'skipped'
                $stageDecision.status = if ($DryRun) { 'dry_run' } else { 'skipped' }
            }
        }
    }

    if (-not $DryRun) {
        $activeContractSports = @(
            @($runManifest.sportRuns) |
                Where-Object { $_ -and ($_.status -in @('ok', 'dry_run')) -and -not [string]::IsNullOrWhiteSpace([string]$_.sport) } |
                ForEach-Object { [string]$_.sport.ToString().ToLowerInvariant() } |
                Select-Object -Unique
        )
        if ($activeContractSports.Count -eq 0) {
            $activeContractSports = @(
                @($sourceSteps) |
                    Where-Object { $_ -and -not [string]::IsNullOrWhiteSpace([string]$_.Sport) } |
                    ForEach-Object { [string]$_.Sport.ToString().ToLowerInvariant() } |
                    Select-Object -Unique
            )
        }
        Write-SimulationContractArtifact -Manifest $runManifest -ActiveSports $activeContractSports
    }

    $runManifest.overallStatus = if ($DryRun) { 'dry_run' } else { 'ok' }
    $runManifest.completedAt = (Get-Date).ToString('o')
    Set-RunTerminalState -Manifest $runManifest -Stage 'completed'
    if ($shouldRunManifestGeneration) {
        Write-RunManifest -Manifest $runManifest
    }
}
catch {
    Set-RunFailureState -Manifest $runManifest -Stage ([string]$runManifest.runState.failedStage) -Message $_.Exception.Message
    $runManifest.completedAt = (Get-Date).ToString('o')
    if ($shouldRunManifestGeneration) {
        Write-RunManifest -Manifest $runManifest
    }
    throw
}
finally {
    $artifactUpdatePaths = @($runManifest.artifactUpdates | ForEach-Object { [string]$_.artifactPath } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
    if ($SkipGitPush) {
        if ($artifactUpdatePaths.Count -eq 0 -and -not $artifactGenerationFallbackToFullPublish) {
            Write-Host 'Artifact stage no-op: no event-level artifact updates were scheduled; skipping artifact publish.' -ForegroundColor Yellow
            foreach ($stageDecision in @($runManifest.stageDecisions | Where-Object { [string]$_.stage -eq 'artifact_generation' })) {
                $stageDecision.decision = 'skipped'
                $stageDecision.status = if ($DryRun) { 'dry_run' } else { 'skipped' }
            }
        }
    }
    elseif ($artifactGenerationFallbackToFullPublish -or $artifactUpdatePaths.Count -eq 0) {
        if ($artifactUpdatePaths.Count -eq 0 -and -not $artifactGenerationFallbackToFullPublish) {
            Write-Host 'Artifact stage no-op: no event-level artifact updates were scheduled; skipping artifact publish.' -ForegroundColor Yellow
            foreach ($stageDecision in @($runManifest.stageDecisions | Where-Object { [string]$_.stage -eq 'artifact_generation' })) {
                $stageDecision.decision = 'skipped'
                $stageDecision.status = if ($DryRun) { 'dry_run' } else { 'skipped' }
            }
        }
        else {
            foreach ($repo in $publishRepos) {
                $result = Invoke-GitPublish -Name $repo.Name -RepoPath $repo.RepoPath -CommitMessage $repo.CommitMessage -RemoteName $GitRemote -ForceIncludePaths (& $resolveForcedPublishArtifactPaths) -DryRun ([bool]$DryRun)
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
    else {
        Write-Host ("Artifact stage incremental: publishing {0} updated event artifact(s)." -f $artifactUpdatePaths.Count) -ForegroundColor Yellow
        foreach ($repo in $publishRepos) {
            $result = Invoke-GitPublish -Name $repo.Name -RepoPath $repo.RepoPath -CommitMessage $repo.CommitMessage -RemoteName $GitRemote -ForceIncludePaths $artifactUpdatePaths -DryRun ([bool]$DryRun)
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