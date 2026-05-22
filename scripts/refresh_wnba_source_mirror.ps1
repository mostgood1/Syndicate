param(
    [string]$Date = (Get-Date).ToString('yyyy-MM-dd'),
    [string]$SourceRepo = "..\WNBA-Betting",
    [switch]$UseExistingMirrorArtifacts
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceRootEnvVar = 'SYNDICATE_SOURCE_ROOT_WNBA'
$sourceRoot = $null
$destDataRoot = Join-Path $repoRoot 'data\wnba_source\data\processed'
$destRawRoot = Join-Path $repoRoot 'data\wnba_source\data\raw'
$destLiveLensRoot = Join-Path $repoRoot 'data\wnba_source\data\live_lens'

if (-not $UseExistingMirrorArtifacts) {
    $sourceRootCandidate = [Environment]::GetEnvironmentVariable($sourceRootEnvVar)
    if ([string]::IsNullOrWhiteSpace($sourceRootCandidate)) {
        $sourceRootCandidate = Join-Path $repoRoot $SourceRepo
    }
    if (-not (Test-Path $sourceRootCandidate)) {
        throw "Source repo path not found: $sourceRootCandidate. Set $sourceRootEnvVar, pass -SourceRepo, or use -UseExistingMirrorArtifacts."
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

    $resolvedSourcePath = (Resolve-Path $SourcePath).Path
    $resolvedDestinationPath = $DestinationPath
    if (Test-Path $DestinationPath) {
        $resolvedDestinationPath = (Resolve-Path $DestinationPath).Path
    }
    if ($resolvedSourcePath -eq $resolvedDestinationPath) {
        return $true
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

$copied = New-Object System.Collections.Generic.List[string]

$files = @(
    "game_cards_$Date.csv",
    "recommendations_$Date.csv",
    "recommendations_slate_$Date.json",
    "cards_sim_detail_$Date.json",
    "cards_props_snapshot_$Date.json",
    "props_recommendations_top_by_game_$Date.json",
    "oddsapi_player_props_$Date.csv",
    "props_predictions_$Date.csv",
    "props_edges_$Date.csv",
    "props_recommendations_$Date.csv",
    "recon_games_$Date.csv",
    "recon_quarters_$Date.csv",
    "recon_props_$Date.csv",
    "recon_players_$Date.csv",
    "boxscores_$Date.csv",
    "live_lens_projections_$Date.jsonl",
    "live_lens_signals_$Date.jsonl",
    "live_lens_tuning_override.json"
)

foreach ($name in $files) {
    $dst = Join-Path $destDataRoot $name
    $src = if ($UseExistingMirrorArtifacts) { $dst } else { Join-Path $sourceRoot (Join-Path 'data\processed' $name) }
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
    $dst = Join-Path $destLiveLensRoot $name
    $src = if ($UseExistingMirrorArtifacts) { $dst } else { Join-Path $sourceRoot (Join-Path 'data\live_lens' $name) }
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst) {
        $copied.Add((Join-Path 'live_lens' $name)) | Out-Null
    }
}

$rawFiles = @(
    "odds_wnba_player_props_$Date.csv",
    "odds_nba_player_props_$Date.csv"
)

foreach ($name in $rawFiles) {
    $dst = Join-Path $destRawRoot $name
    $src = if ($UseExistingMirrorArtifacts) { $dst } else { Join-Path $sourceRoot (Join-Path 'data\raw' $name) }
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst) {
        $copied.Add((Join-Path 'raw' $name)) | Out-Null
    }
}

$artifactGroups = [ordered]@{
    processed = 0
    live_lens = 0
    raw = 0
    other = 0
}

foreach ($artifact in $copied) {
    if ($artifact.StartsWith('live_lens\')) {
        $artifactGroups.live_lens += 1
    }
    elseif ($artifact.StartsWith('raw\')) {
        $artifactGroups.raw += 1
    }
    elseif ($artifact.IndexOf('\') -lt 0) {
        $artifactGroups.processed += 1
    }
    else {
        $artifactGroups.other += 1
    }
}

$manifest = [pscustomobject]@{
    sport = 'wnba'
    date = $Date
    refreshedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
    sourceRepo = $sourceRoot
    sourceRootEnvVar = $sourceRootEnvVar
    destinationRoot = $destDataRoot
    usedExistingMirrorArtifacts = [bool]$UseExistingMirrorArtifacts
    copiedArtifactCount = $copied.Count
    artifactGroups = [pscustomobject]$artifactGroups
    copiedArtifacts = @($copied)
}

$manifestRoot = Join-Path $repoRoot 'data\wnba_source\manifests'
$manifestPath = Join-Path $manifestRoot ("mirror_refresh_{0}.json" -f $Date)
$latestManifestPath = Join-Path $manifestRoot 'mirror_refresh_latest.json'

Write-JsonFile -Path $manifestPath -Value $manifest
Write-JsonFile -Path $latestManifestPath -Value $manifest

$manifest | ConvertTo-Json -Depth 6