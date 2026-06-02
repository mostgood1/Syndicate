param(
    [string]$Date,
    [string]$SourceRepo = "",
    [string]$SourceArtifactRoot = "",
    [switch]$UseExistingMirrorArtifacts
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Date)) {
    $centralTZ = [TimeZoneInfo]::FindSystemTimeZoneById("Central Standard Time")
    $Date = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $centralTZ).ToString('yyyy-MM-dd')
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceRootEnvVar = 'SYNDICATE_SOURCE_ROOT_NHL'
$sourceArtifactRootEnvVar = 'SYNDICATE_ARTIFACT_ROOT_NHL'

function Get-EnvOverride {
    param(
        [string[]]$Names
    )

    foreach ($name in $Names) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value
        }
    }

    return ''
}

function Resolve-DestinationSportRoot {
    param(
        [string]$LocalDirName,
        [string[]]$ExplicitRootEnvVars
    )

    $explicitRoot = Get-EnvOverride -Names $ExplicitRootEnvVars
    if (-not [string]::IsNullOrWhiteSpace($explicitRoot)) {
        return [System.IO.Path]::GetFullPath($explicitRoot)
    }

    $dataRoot = Get-EnvOverride -Names @('SYNDICATE_DATA_ROOT')
    if (-not [string]::IsNullOrWhiteSpace($dataRoot)) {
        return [System.IO.Path]::GetFullPath((Join-Path $dataRoot $LocalDirName))
    }

    return Join-Path $repoRoot (Join-Path 'data' $LocalDirName)
}

$sourceRoot = $null
$artifactRoot = $null
$destinationSportRoot = Resolve-DestinationSportRoot -LocalDirName 'nhl_source' -ExplicitRootEnvVars @('SYNDICATE_NHL_SOURCE_ROOT')
$destDataRoot = Join-Path $destinationSportRoot 'data\processed'
$destLiveLensRoot = Join-Path $destinationSportRoot 'data\live_lens'
$destOddsRoot = Join-Path $destinationSportRoot (Join-Path 'data\odds\games' ("date=" + $Date))
$destTeamOddsRoot = Join-Path $destinationSportRoot (Join-Path 'data\odds\team' ("date=" + $Date))
$destPropsRoot = Join-Path $destinationSportRoot (Join-Path 'data\props\player_props_lines' ("date=" + $Date))

if (-not $UseExistingMirrorArtifacts) {
    $artifactRootCandidate = $SourceArtifactRoot
    if ([string]::IsNullOrWhiteSpace($artifactRootCandidate)) {
        $artifactRootCandidate = [Environment]::GetEnvironmentVariable($sourceArtifactRootEnvVar)
    }
    if (-not [string]::IsNullOrWhiteSpace($artifactRootCandidate)) {
        if (-not (Test-Path $artifactRootCandidate)) {
            throw "Artifact root path not found: $artifactRootCandidate. Set $sourceArtifactRootEnvVar or pass -SourceArtifactRoot with a published NHL artifact bundle path."
        }
        $artifactRoot = (Resolve-Path $artifactRootCandidate).Path
    }
}

if ((-not $UseExistingMirrorArtifacts) -and (-not $artifactRoot)) {
    $sourceRootCandidate = [Environment]::GetEnvironmentVariable($sourceRootEnvVar)
    if ([string]::IsNullOrWhiteSpace($sourceRootCandidate)) {
        $sourceRootCandidate = Join-Path $repoRoot $SourceRepo
    }
    if (-not (Test-Path $sourceRootCandidate)) {
        throw "Source repo path not found: $sourceRootCandidate. Set $sourceRootEnvVar, pass -SourceRepo, set $sourceArtifactRootEnvVar / -SourceArtifactRoot, or use -UseExistingMirrorArtifacts."
    }
    $sourceRoot = (Resolve-Path $sourceRootCandidate).Path
}

function Copy-IfExists {
    param(
        [string]$SourcePath,
        [string]$DestinationPath
    )

    if (-not (Test-Path $SourcePath)) {
        return $false
    }

    $parent = Split-Path -Parent $DestinationPath
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    Copy-Item -Path $SourcePath -Destination $DestinationPath -Force
    return $true
}

function Copy-TreeIfExists {
    param(
        [string]$SourcePath,
        [string]$DestinationPath
    )

    if (-not (Test-Path $SourcePath)) {
        return $false
    }

    $parent = Split-Path -Parent $DestinationPath
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    Copy-Item -Path $SourcePath -Destination $DestinationPath -Recurse -Force
    return $true
}

function Write-JsonFile {
    param(
        [string]$Path,
        $Value
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    $Value | ConvertTo-Json -Depth 6 | Set-Content -Path $Path -Encoding utf8
}

function Copy-FirstExisting {
    param(
        [string[]]$SourcePaths,
        [string]$DestinationPath
    )

    foreach ($SourcePath in $SourcePaths) {
        if (Copy-IfExists -SourcePath $SourcePath -DestinationPath $DestinationPath) {
            return $true
        }
    }

    return $false
}

function Add-IfExists {
    param(
        [string]$SourcePath,
        [string]$ArtifactLabel,
        [System.Collections.Generic.List[string]]$TargetList
    )

    if (Test-Path $SourcePath) {
        $TargetList.Add($ArtifactLabel) | Out-Null
        return $true
    }

    return $false
}

$copied = New-Object System.Collections.Generic.List[string]

$files = @(
    "predictions_$Date.csv",
    "predictions_sim_$Date.csv",
    "recommendations_$Date.csv",
    "recommendations_sim_$Date.csv",
    "reconciliations_log.csv",
    "props_reconciliations_log.csv",
    "recon_games_$Date.csv",
    "recon_props_$Date.csv",
    "props_projections_all_$Date.csv",
    "props_boxscores_sim_$Date.csv",
    "props_boxscores_sim_hist_$Date.csv",
    "props_boxscores_sim_samples_$Date.csv",
    "props_predictions_$Date.csv",
    "props_recommendations_$Date.csv",
    "roster_snapshot_$Date.csv",
    "injuries_$Date.csv",
    "lineups_$Date.csv",
    "lineups_co_toi_$Date.csv",
    "shifts_$Date.csv",
    "co_toi_shifts_$Date.csv",
    "starting_goalies_$Date.csv",
    "smart_sim_${Date}_bundle.json"
)

foreach ($name in $files) {
    $dst = Join-Path $destDataRoot $name
    if ($UseExistingMirrorArtifacts) {
        Add-IfExists -SourcePath $dst -ArtifactLabel $name -TargetList $copied | Out-Null
    }
    else {
        $src = if ($artifactRoot) { Join-Path $artifactRoot (Join-Path 'data\processed' $name) } else { Join-Path $sourceRoot (Join-Path 'data\processed' $name) }
        if (Copy-IfExists -SourcePath $src -DestinationPath $dst) {
            $copied.Add($name) | Out-Null
        }
    }
}

$liveLensFiles = @(
    "live_lens_projections_$Date.jsonl",
    "live_lens_signals_$Date.jsonl",
    "live_lens_tuning_override.json"
)

foreach ($name in $liveLensFiles) {
    $processedDst = Join-Path $destDataRoot $name
    $liveLensDst = Join-Path $destLiveLensRoot $name
    if ($UseExistingMirrorArtifacts) {
        if (Add-IfExists -SourcePath $processedDst -ArtifactLabel $name -TargetList $copied) {
        }
        if (Add-IfExists -SourcePath $liveLensDst -ArtifactLabel (Join-Path 'live_lens' $name) -TargetList $copied) {
        }
    }
    else {
        $sources = @(
            ($(if ($artifactRoot) { Join-Path $artifactRoot (Join-Path 'data\processed' $name) } else { Join-Path $sourceRoot (Join-Path 'data\processed' $name) })),
            ($(if ($artifactRoot) { Join-Path $artifactRoot (Join-Path 'data\processed\live_lens' $name) } else { Join-Path $sourceRoot (Join-Path 'data\processed\live_lens' $name) })),
            ($(if ($artifactRoot) { Join-Path $artifactRoot (Join-Path 'data\live_lens' $name) } else { Join-Path $sourceRoot (Join-Path 'data\live_lens' $name) }))
        )
        if (Copy-FirstExisting -SourcePaths $sources -DestinationPath $processedDst) {
            $copied.Add($name) | Out-Null
        }
        if (Copy-FirstExisting -SourcePaths $sources -DestinationPath $liveLensDst) {
            $copied.Add((Join-Path 'live_lens' $name)) | Out-Null
        }
    }
}

$scoreboardDst = Join-Path $destOddsRoot 'scoreboard.csv'
if (($UseExistingMirrorArtifacts -and (Test-Path $scoreboardDst)) -or ((-not $UseExistingMirrorArtifacts) -and (Copy-IfExists -SourcePath (Join-Path ($(if ($artifactRoot) { $artifactRoot } else { $sourceRoot })) (Join-Path 'data\odds\games' ("date=" + $Date + '\\scoreboard.csv'))) -DestinationPath $scoreboardDst))) {
    $copied.Add((Join-Path (Join-Path 'odds\games' ("date=" + $Date)) 'scoreboard.csv')) | Out-Null
}

$teamOddsFiles = @('oddsapi.csv', 'oddsapi.parquet')
foreach ($name in $teamOddsFiles) {
    $dst = Join-Path $destTeamOddsRoot $name
    if (($UseExistingMirrorArtifacts -and (Test-Path $dst)) -or ((-not $UseExistingMirrorArtifacts) -and (Copy-IfExists -SourcePath (Join-Path ($(if ($artifactRoot) { $artifactRoot } else { $sourceRoot })) (Join-Path 'data\odds\team' ("date=" + $Date + ('\\' + $name)))) -DestinationPath $dst))) {
        $copied.Add((Join-Path (Join-Path 'odds\team' ("date=" + $Date)) $name)) | Out-Null
    }
}

$propsFiles = @('oddsapi.csv', 'oddsapi.parquet')
foreach ($name in $propsFiles) {
    $dst = Join-Path $destPropsRoot $name
    if (($UseExistingMirrorArtifacts -and (Test-Path $dst)) -or ((-not $UseExistingMirrorArtifacts) -and (Copy-IfExists -SourcePath (Join-Path ($(if ($artifactRoot) { $artifactRoot } else { $sourceRoot })) (Join-Path 'data\props\player_props_lines' ("date=" + $Date + ('\\' + $name)))) -DestinationPath $dst))) {
        $copied.Add((Join-Path (Join-Path 'props\player_props_lines' ("date=" + $Date)) $name)) | Out-Null
    }
}

$artifactGroups = [ordered]@{
    processed = 0
    live_lens = 0
    odds = 0
    props = 0
    other = 0
}

foreach ($artifact in $copied) {
    if ($artifact.StartsWith('live_lens\')) {
        $artifactGroups.live_lens += 1
    }
    elseif ($artifact.StartsWith('odds\')) {
        $artifactGroups.odds += 1
    }
    elseif ($artifact.StartsWith('props\')) {
        $artifactGroups.props += 1
    }
    elseif ($artifact.IndexOf('\') -lt 0) {
        $artifactGroups.processed += 1
    }
    else {
        $artifactGroups.other += 1
    }
}

$manifest = [pscustomobject]@{
    sport = 'nhl'
    date = $Date
    refreshedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
    sourceRepo = $sourceRoot
    sourceArtifactRoot = $artifactRoot
    sourceRootEnvVar = $sourceRootEnvVar
    sourceArtifactRootEnvVar = $sourceArtifactRootEnvVar
    destinationRoot = $destinationSportRoot
    usedExistingMirrorArtifacts = [bool]$UseExistingMirrorArtifacts
    usedArtifactBundle = [bool](-not [string]::IsNullOrWhiteSpace($artifactRoot))
    copiedArtifactCount = $copied.Count
    artifactGroups = [pscustomobject]$artifactGroups
    copiedArtifacts = @($copied)
}

$manifestRoot = Join-Path $destinationSportRoot 'manifests'
$manifestPath = Join-Path $manifestRoot ("mirror_refresh_{0}.json" -f $Date)
$latestManifestPath = Join-Path $manifestRoot 'mirror_refresh_latest.json'

Write-JsonFile -Path $manifestPath -Value $manifest
Write-JsonFile -Path $latestManifestPath -Value $manifest

$manifest | ConvertTo-Json -Depth 6