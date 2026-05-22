param(
    [string]$Date = (Get-Date).ToString('yyyy-MM-dd'),
    [string]$SourceRepo = "..\NHL-Betting"
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceRootEnvVar = 'SYNDICATE_SOURCE_ROOT_NHL'
$sourceRootCandidate = [Environment]::GetEnvironmentVariable($sourceRootEnvVar)
if ([string]::IsNullOrWhiteSpace($sourceRootCandidate)) {
    $sourceRootCandidate = Join-Path $repoRoot $SourceRepo
}
if (-not (Test-Path $sourceRootCandidate)) {
    throw "Source repo path not found: $sourceRootCandidate. Set $sourceRootEnvVar or pass -SourceRepo."
}
$sourceRoot = (Resolve-Path $sourceRootCandidate).Path
$destDataRoot = Join-Path $repoRoot 'data\nhl_source\data\processed'
$destLiveLensRoot = Join-Path $repoRoot 'data\nhl_source\data\live_lens'
$destOddsRoot = Join-Path $repoRoot (Join-Path 'data\nhl_source\data\odds\games' ("date=" + $Date))
$destTeamOddsRoot = Join-Path $repoRoot (Join-Path 'data\nhl_source\data\odds\team' ("date=" + $Date))
$destPropsRoot = Join-Path $repoRoot (Join-Path 'data\nhl_source\data\props\player_props_lines' ("date=" + $Date))

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
    "props_boxscores_sim_$Date.csv",
    "props_boxscores_sim_hist_$Date.csv",
    "props_recommendations_$Date.csv"
)

foreach ($name in $files) {
    $src = Join-Path $sourceRoot (Join-Path 'data\processed' $name)
    $dst = Join-Path $destDataRoot $name
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst) {
        $copied.Add($name) | Out-Null
    }
}

$liveLensFiles = @(
    "live_lens_projections_$Date.jsonl",
    "live_lens_signals_$Date.jsonl",
    "live_lens_tuning_override.json"
)

foreach ($name in $liveLensFiles) {
    $sources = @(
        (Join-Path $sourceRoot (Join-Path 'data\processed' $name)),
        (Join-Path $sourceRoot (Join-Path 'data\processed\live_lens' $name)),
        (Join-Path $sourceRoot (Join-Path 'data\live_lens' $name))
    )
    if (Copy-FirstExisting -SourcePaths $sources -DestinationPath (Join-Path $destDataRoot $name)) {
        $copied.Add($name) | Out-Null
    }
    if (Copy-FirstExisting -SourcePaths $sources -DestinationPath (Join-Path $destLiveLensRoot $name)) {
        $copied.Add((Join-Path 'live_lens' $name)) | Out-Null
    }
}

$scoreboardSrc = Join-Path $sourceRoot (Join-Path 'data\odds\games' ("date=" + $Date + '\\scoreboard.csv'))
$scoreboardDst = Join-Path $destOddsRoot 'scoreboard.csv'
if (Copy-IfExists -SourcePath $scoreboardSrc -DestinationPath $scoreboardDst) {
    $copied.Add((Join-Path (Join-Path 'odds\games' ("date=" + $Date)) 'scoreboard.csv')) | Out-Null
}

$teamOddsFiles = @('oddsapi.csv', 'oddsapi.parquet')
foreach ($name in $teamOddsFiles) {
    $src = Join-Path $sourceRoot (Join-Path 'data\odds\team' ("date=" + $Date + ('\\' + $name)))
    $dst = Join-Path $destTeamOddsRoot $name
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst) {
        $copied.Add((Join-Path (Join-Path 'odds\team' ("date=" + $Date)) $name)) | Out-Null
    }
}

$propsFiles = @('oddsapi.csv', 'oddsapi.parquet')
foreach ($name in $propsFiles) {
    $src = Join-Path $sourceRoot (Join-Path 'data\props\player_props_lines' ("date=" + $Date + ('\\' + $name)))
    $dst = Join-Path $destPropsRoot $name
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst) {
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
    sourceRootEnvVar = $sourceRootEnvVar
    destinationRoot = (Join-Path $repoRoot 'data\nhl_source')
    copiedArtifactCount = $copied.Count
    artifactGroups = [pscustomobject]$artifactGroups
    copiedArtifacts = @($copied)
}

$manifestRoot = Join-Path $repoRoot 'data\nhl_source\manifests'
$manifestPath = Join-Path $manifestRoot ("mirror_refresh_{0}.json" -f $Date)
$latestManifestPath = Join-Path $manifestRoot 'mirror_refresh_latest.json'

Write-JsonFile -Path $manifestPath -Value $manifest
Write-JsonFile -Path $latestManifestPath -Value $manifest

$manifest | ConvertTo-Json -Depth 6