param(
    [string]$Date = (Get-Date).ToString('yyyy-MM-dd'),
    [string]$SourceRepo = "..\NBA-Betting"
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceRootEnvVar = 'SYNDICATE_SOURCE_ROOT_NBA'
$sourceRootCandidate = [Environment]::GetEnvironmentVariable($sourceRootEnvVar)
if ([string]::IsNullOrWhiteSpace($sourceRootCandidate)) {
    $sourceRootCandidate = Join-Path $repoRoot $SourceRepo
}
if (-not (Test-Path $sourceRootCandidate)) {
    throw "Source repo path not found: $sourceRootCandidate. Set $sourceRootEnvVar or pass -SourceRepo."
}
$sourceRoot = (Resolve-Path $sourceRootCandidate).Path
$destDataRoot = Join-Path $repoRoot 'data\nba_source\data\processed'
$destRawRoot = Join-Path $repoRoot 'data\nba_source\data\raw'
$destWebRoot = Join-Path $repoRoot 'data\nba_source\web'
$destLiveLensRoot = Join-Path $repoRoot 'data\nba_source\data\live_lens'
$destLiveSnapshotsRoot = Join-Path $repoRoot 'data\nba_source\data\processed\live_snapshots'
$targetDate = [datetime]::ParseExact($Date, 'yyyy-MM-dd', $null)
$targetSeason = $targetDate.Year

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

function Get-LatestDatedArtifactPath {
    param(
        [string]$SourceDirectory,
        [string]$Prefix,
        [string]$Suffix,
        [datetime]$TargetDate
    )

    if (-not (Test-Path $SourceDirectory)) {
        return $null
    }

    $escapedPrefix = [regex]::Escape($Prefix)
    $escapedSuffix = [regex]::Escape($Suffix)
    $pattern = '^{0}(?<date>\d{{4}}-\d{{2}}-\d{{2}}){1}$' -f $escapedPrefix, $escapedSuffix
    $bestPath = $null
    $bestDate = $null

    foreach ($candidate in Get-ChildItem -Path $SourceDirectory -File) {
        $match = [regex]::Match($candidate.Name, $pattern)
        if (-not $match.Success) {
            continue
        }

        try {
            $candidateDate = [datetime]::ParseExact($match.Groups['date'].Value, 'yyyy-MM-dd', $null)
        }
        catch {
            continue
        }

        if ($candidateDate -gt $TargetDate) {
            continue
        }

        if ($null -eq $bestDate -or $candidateDate -gt $bestDate) {
            $bestDate = $candidateDate
            $bestPath = $candidate.FullName
        }
    }

    return $bestPath
}

function Copy-LatestDatedArtifact {
    param(
        [string]$SourceDirectory,
        [string]$DestinationDirectory,
        [string]$Prefix,
        [string]$Suffix,
        [datetime]$TargetDate,
        [string]$ManifestPrefix = ''
    )

    $sourcePath = Get-LatestDatedArtifactPath -SourceDirectory $SourceDirectory -Prefix $Prefix -Suffix $Suffix -TargetDate $TargetDate
    if (-not $sourcePath) {
        return $false
    }

    $fileName = Split-Path -Leaf $sourcePath
    $destinationPath = Join-Path $DestinationDirectory $fileName
    if (-not (Copy-IfExists -SourcePath $sourcePath -DestinationPath $destinationPath)) {
        return $false
    }

    if ([string]::IsNullOrWhiteSpace($ManifestPrefix)) {
        $copied.Add($fileName) | Out-Null
    }
    else {
        $copied.Add((Join-Path $ManifestPrefix $fileName)) | Out-Null
    }

    return $true
}

function Ensure-LiveStateSnapshot {
    param(
        [string]$SourceRoot,
        [string]$Date,
        [string]$LiveLensDir
    )

    $snapshotPath = Join-Path $SourceRoot (Join-Path 'data\processed\live_snapshots' ("live_state_{0}.jsonl" -f $Date))
    if (Test-Path $snapshotPath) {
        return $snapshotPath
    }

    $sourcePython = Join-Path $SourceRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $sourcePython)) {
        return $null
    }

    $tmpPy = Join-Path ([System.IO.Path]::GetTempPath()) ("syndicate_emit_nba_live_state_{0}_{1}.py" -f $Date, [guid]::NewGuid().ToString('N'))
    try {
        $script = @"
import os
import sys
from pathlib import Path

repo_root = Path(r'{REPO_ROOT}')
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

os.environ['NBA_LIVE_LENS_DIR'] = r'{LIVE_LENS_DIR}'
os.environ['LIVE_LENS_SNAPSHOTS'] = '1'

import app

date_str = r'{DATE}'
client = app.app.test_client()
resp = client.get(f'/api/live_state?date={date_str}&ttl=12')
if resp is None or int(resp.status_code or 0) >= 400:
    raise RuntimeError(f'/api/live_state failed for {date_str}: {getattr(resp, "status_code", None)}')
print('OK')
"@
        $script = $script.Replace('{REPO_ROOT}', $SourceRoot)
        $script = $script.Replace('{LIVE_LENS_DIR}', $LiveLensDir)
        $script = $script.Replace('{DATE}', $Date)
        Set-Content -Path $tmpPy -Value $script -Encoding UTF8
        & $sourcePython $tmpPy | Out-Null
    }
    catch {
        return $null
    }
    finally {
        Remove-Item -Path $tmpPy -ErrorAction SilentlyContinue
    }

    if (Test-Path $snapshotPath) {
        return $snapshotPath
    }
    return $null
}

$copied = New-Object System.Collections.Generic.List[string]

$datedProcessedArtifacts = @(
    @{ Prefix = 'game_cards_'; Suffix = '.csv' },
    @{ Prefix = 'recommendations_'; Suffix = '.csv' },
    @{ Prefix = 'recommendations_slate_'; Suffix = '.json' },
    @{ Prefix = 'cards_sim_detail_'; Suffix = '.json' },
    @{ Prefix = 'cards_props_snapshot_'; Suffix = '.json' },
    @{ Prefix = 'props_recommendations_top_by_game_'; Suffix = '.json' },
    @{ Prefix = 'oddsapi_player_props_'; Suffix = '.csv' },
    @{ Prefix = 'props_predictions_'; Suffix = '.csv' },
    @{ Prefix = 'props_edges_'; Suffix = '.csv' },
    @{ Prefix = 'props_recommendations_'; Suffix = '.csv' },
    @{ Prefix = 'recon_games_'; Suffix = '.csv' },
    @{ Prefix = 'recon_quarters_'; Suffix = '.csv' },
    @{ Prefix = 'recon_props_'; Suffix = '.csv' },
    @{ Prefix = 'recon_players_'; Suffix = '.csv' },
    @{ Prefix = 'boxscores_'; Suffix = '.csv' },
    @{ Prefix = 'live_lens_projections_'; Suffix = '.jsonl' },
    @{ Prefix = 'live_lens_signals_'; Suffix = '.jsonl' }
)

foreach ($artifact in $datedProcessedArtifacts) {
    Copy-LatestDatedArtifact -SourceDirectory (Join-Path $sourceRoot 'data\processed') -DestinationDirectory $destDataRoot -Prefix $artifact.Prefix -Suffix $artifact.Suffix -TargetDate $targetDate | Out-Null
}

$processedStaticFiles = @(
    'live_lens_tuning_override.json',
    ("season_betting_card_manifest_{0}_retuned.json" -f $targetSeason)
)

foreach ($name in $processedStaticFiles) {
    $src = Join-Path $sourceRoot (Join-Path 'data\processed' $name)
    $dst = Join-Path $destDataRoot $name
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst) {
        $copied.Add($name) | Out-Null
    }
}

$dataStaticFiles = @(
    'features_catalog.json'
)

foreach ($name in $dataStaticFiles) {
    $src = Join-Path $sourceRoot (Join-Path 'data' $name)
    $dst = Join-Path (Join-Path $repoRoot 'data\nba_source\data') $name
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst) {
        $copied.Add((Join-Path 'data' $name)) | Out-Null
    }
}

$seasonBettingCardArtifacts = @(
    @{ Prefix = ("season_betting_card_manifest_{0}_retuned_" -f $targetSeason); Suffix = '.json' },
    @{ Prefix = ("season_betting_card_day_{0}_retuned_" -f $targetSeason); Suffix = '.json' },
    @{ Prefix = ("season_betting_card_day_{0}_retuned_" -f $targetSeason); Suffix = '_insights.json' }
)

foreach ($artifact in $seasonBettingCardArtifacts) {
    Copy-LatestDatedArtifact -SourceDirectory (Join-Path $sourceRoot 'data\processed') -DestinationDirectory $destDataRoot -Prefix $artifact.Prefix -Suffix $artifact.Suffix -TargetDate $targetDate | Out-Null
}

$datedLiveLensArtifacts = @(
    @{ Prefix = 'live_lens_projections_'; Suffix = '.jsonl' },
    @{ Prefix = 'live_lens_signals_'; Suffix = '.jsonl' }
)

foreach ($artifact in $datedLiveLensArtifacts) {
    Copy-LatestDatedArtifact -SourceDirectory (Join-Path $sourceRoot 'data\live_lens') -DestinationDirectory $destLiveLensRoot -Prefix $artifact.Prefix -Suffix $artifact.Suffix -TargetDate $targetDate -ManifestPrefix 'live_lens' | Out-Null
}

$liveLensStaticFiles = @(
    'live_lens_tuning_override.json'
)

foreach ($name in $liveLensStaticFiles) {
    $src = Join-Path $sourceRoot (Join-Path 'data\live_lens' $name)
    $dst = Join-Path $destLiveLensRoot $name
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst) {
        $copied.Add((Join-Path 'live_lens' $name)) | Out-Null
    }
}

$datedLiveSnapshotArtifacts = @(
    @{ Prefix = 'live_state_'; Suffix = '.jsonl' },
    @{ Prefix = 'live_pbp_stats_'; Suffix = '.jsonl' },
    @{ Prefix = 'live_lines_'; Suffix = '.jsonl' },
    @{ Prefix = 'live_player_boxscore_'; Suffix = '.jsonl' },
    @{ Prefix = 'live_player_lens_'; Suffix = '.jsonl' }
)

[void](Ensure-LiveStateSnapshot -SourceRoot $sourceRoot -Date $Date -LiveLensDir (Join-Path $sourceRoot 'data\processed'))

foreach ($artifact in $datedLiveSnapshotArtifacts) {
    Copy-LatestDatedArtifact -SourceDirectory (Join-Path $sourceRoot 'data\processed\live_snapshots') -DestinationDirectory $destLiveSnapshotsRoot -Prefix $artifact.Prefix -Suffix $artifact.Suffix -TargetDate $targetDate -ManifestPrefix 'live_snapshots' | Out-Null
}

$datedRawArtifacts = @(
    @{ Prefix = 'odds_nba_player_props_'; Suffix = '.csv' }
)

foreach ($artifact in $datedRawArtifacts) {
    Copy-LatestDatedArtifact -SourceDirectory (Join-Path $sourceRoot 'data\raw') -DestinationDirectory $destRawRoot -Prefix $artifact.Prefix -Suffix $artifact.Suffix -TargetDate $targetDate -ManifestPrefix 'raw' | Out-Null
}

$webFiles = @(
    "betting-card-v2.css",
    "betting-card-v2.js"
)

foreach ($name in $webFiles) {
    $src = Join-Path $sourceRoot (Join-Path 'web' $name)
    $dst = Join-Path $destWebRoot $name
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst) {
        $copied.Add((Join-Path 'web' $name)) | Out-Null
    }
}

$artifactGroups = [ordered]@{
    processed = 0
    live_lens = 0
    raw = 0
    web = 0
    other = 0
}

foreach ($artifact in $copied) {
    if ($artifact.StartsWith('live_lens\') -or $artifact.StartsWith('live_lens_')) {
        $artifactGroups.live_lens += 1
    }
    elseif ($artifact.StartsWith('live_snapshots\')) {
        $artifactGroups.live_lens += 1
    }
    elseif ($artifact.StartsWith('raw\')) {
        $artifactGroups.raw += 1
    }
    elseif ($artifact.StartsWith('web\')) {
        $artifactGroups.web += 1
    }
    elseif ($artifact.IndexOf('\') -lt 0) {
        $artifactGroups.processed += 1
    }
    else {
        $artifactGroups.other += 1
    }
}

$manifest = [pscustomobject]@{
    sport = 'nba'
    date = $Date
    refreshedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
    sourceRepo = $sourceRoot
    sourceRootEnvVar = $sourceRootEnvVar
    destinationRoot = (Join-Path $repoRoot 'data\nba_source')
    copiedArtifactCount = $copied.Count
    artifactGroups = [pscustomobject]$artifactGroups
    copiedArtifacts = @($copied)
}

$manifestRoot = Join-Path $repoRoot 'data\nba_source\manifests'
$manifestPath = Join-Path $manifestRoot ("mirror_refresh_{0}.json" -f $Date)
$latestManifestPath = Join-Path $manifestRoot 'mirror_refresh_latest.json'

Write-JsonFile -Path $manifestPath -Value $manifest
Write-JsonFile -Path $latestManifestPath -Value $manifest

$manifest | ConvertTo-Json -Depth 6