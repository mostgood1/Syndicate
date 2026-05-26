param(
    [string]$Date = (Get-Date).ToString('yyyy-MM-dd'),
    [string]$SourceRepo = "",
    [string]$SourceArtifactRoot = "",
    [switch]$UseExistingMirrorArtifacts
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Date)) {
    $Date = (Get-Date).ToString('yyyy-MM-dd')
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceRootEnvVar = 'SYNDICATE_SOURCE_ROOT_NBA'
$sourceArtifactRootEnvVar = 'SYNDICATE_ARTIFACT_ROOT_NBA'
$sourceRoot = $null
$artifactRoot = $null
$destDataRoot = Join-Path $repoRoot 'data\nba_source\data\processed'
$destRawRoot = Join-Path $repoRoot 'data\nba_source\data\raw'
$destWebRoot = Join-Path $repoRoot 'data\nba_source\web'
$destLiveLensRoot = Join-Path $repoRoot 'data\nba_source\data\live_lens'
$destLiveSnapshotsRoot = Join-Path $repoRoot 'data\nba_source\data\processed\live_snapshots'
$targetDate = [datetime]::ParseExact($Date, 'yyyy-MM-dd', $null)
$targetSeason = $targetDate.Year

if (-not $UseExistingMirrorArtifacts) {
    $artifactRootCandidate = $SourceArtifactRoot
    if ([string]::IsNullOrWhiteSpace($artifactRootCandidate)) {
        $artifactRootCandidate = [Environment]::GetEnvironmentVariable($sourceArtifactRootEnvVar)
    }
    if (-not [string]::IsNullOrWhiteSpace($artifactRootCandidate)) {
        if (-not (Test-Path $artifactRootCandidate)) {
            throw "Artifact root path not found: $artifactRootCandidate. Set $sourceArtifactRootEnvVar or pass -SourceArtifactRoot with a published NBA artifact bundle path."
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

function Copy-MatchingDatedArtifacts {
    param(
        [string]$SourceDirectory,
        [string]$DestinationDirectory,
        [string]$Prefix,
        [string]$Suffix,
        [datetime]$TargetDate,
        [string]$ManifestPrefix = ''
    )

    if (-not (Test-Path $SourceDirectory)) {
        return 0
    }

    $escapedPrefix = [regex]::Escape($Prefix)
    $escapedSuffix = [regex]::Escape($Suffix)
    $pattern = '^{0}(?<date>\d{{4}}-\d{{2}}-\d{{2}}){1}$' -f $escapedPrefix, $escapedSuffix
    $copiedCount = 0

    foreach ($candidate in Get-ChildItem -Path $SourceDirectory -File | Sort-Object Name) {
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

        $destinationPath = Join-Path $DestinationDirectory $candidate.Name
        if (-not (Copy-IfExists -SourcePath $candidate.FullName -DestinationPath $destinationPath)) {
            continue
        }

        if ([string]::IsNullOrWhiteSpace($ManifestPrefix)) {
            if (-not $copied.Contains($candidate.Name)) {
                $copied.Add($candidate.Name) | Out-Null
            }
        }
        else {
            $manifestName = Join-Path $ManifestPrefix $candidate.Name
            if (-not $copied.Contains($manifestName)) {
                $copied.Add($manifestName) | Out-Null
            }
        }
        $copiedCount += 1
    }

    return $copiedCount
}

$copied = New-Object System.Collections.Generic.List[string]

$datedProcessedArtifacts = @(
    @{ Prefix = 'game_cards_'; Suffix = '.csv' },
    @{ Prefix = 'recommendations_'; Suffix = '.csv' },
    @{ Prefix = 'recommendations_slate_'; Suffix = '.json' },
    @{ Prefix = 'cards_sim_detail_'; Suffix = '.json' },
    @{ Prefix = 'cards_props_snapshot_'; Suffix = '.json' },
    @{ Prefix = 'props_recommendations_top_by_game_'; Suffix = '.json' },
    @{ Prefix = 'smart_sim_'; Suffix = '.json' },
    @{ Prefix = 'oddsapi_player_props_'; Suffix = '.csv' },
    @{ Prefix = 'props_predictions_'; Suffix = '.csv' },
    @{ Prefix = 'props_edges_'; Suffix = '.csv' },
    @{ Prefix = 'props_recommendations_'; Suffix = '.csv' },
    @{ Prefix = 'recon_games_'; Suffix = '.csv' },
    @{ Prefix = 'recon_quarters_'; Suffix = '.csv' },
    @{ Prefix = 'recon_props_'; Suffix = '.csv' },
    @{ Prefix = 'recon_players_'; Suffix = '.csv' },
    @{ Prefix = 'live_player_lens_tuning_'; Suffix = '.csv' },
    @{ Prefix = 'boxscores_'; Suffix = '.csv' },
    @{ Prefix = 'live_lens_projections_'; Suffix = '.jsonl' },
    @{ Prefix = 'live_lens_signals_'; Suffix = '.jsonl' }
)

foreach ($artifact in $datedProcessedArtifacts) {
    $sourceDirectory = if ($UseExistingMirrorArtifacts) { $destDataRoot } elseif ($artifactRoot) { Join-Path $artifactRoot 'data\processed' } else { Join-Path $sourceRoot 'data\processed' }
    Copy-LatestDatedArtifact -SourceDirectory $sourceDirectory -DestinationDirectory $destDataRoot -Prefix $artifact.Prefix -Suffix $artifact.Suffix -TargetDate $targetDate | Out-Null
}

$boxscoresSourceDirectory = if ($UseExistingMirrorArtifacts) { $destDataRoot } elseif ($artifactRoot) { Join-Path $artifactRoot 'data\processed' } else { Join-Path $sourceRoot 'data\processed' }
Copy-MatchingDatedArtifacts -SourceDirectory $boxscoresSourceDirectory -DestinationDirectory $destDataRoot -Prefix 'boxscores_' -Suffix '.csv' -TargetDate $targetDate | Out-Null

$processedStaticFiles = @(
    'live_lens_tuning_override.json',
    'boxscores_history.csv',
    ("season_betting_card_manifest_{0}_retuned.json" -f $targetSeason)
)

foreach ($name in $processedStaticFiles) {
    $dst = Join-Path $destDataRoot $name
    if (($UseExistingMirrorArtifacts -and (Test-Path $dst)) -or ((-not $UseExistingMirrorArtifacts) -and (Copy-IfExists -SourcePath (Join-Path ($(if ($artifactRoot) { $artifactRoot } else { $sourceRoot })) (Join-Path 'data\processed' $name)) -DestinationPath $dst))) {
        $copied.Add($name) | Out-Null
    }
}

$dataStaticFiles = @(
    'features_catalog.json'
)

foreach ($name in $dataStaticFiles) {
    $dst = Join-Path (Join-Path $repoRoot 'data\nba_source\data') $name
    if (($UseExistingMirrorArtifacts -and (Test-Path $dst)) -or ((-not $UseExistingMirrorArtifacts) -and (Copy-IfExists -SourcePath (Join-Path ($(if ($artifactRoot) { $artifactRoot } else { $sourceRoot })) (Join-Path 'data' $name)) -DestinationPath $dst))) {
        $copied.Add((Join-Path 'data' $name)) | Out-Null
    }
}

$seasonBettingCardArtifacts = @(
    @{ Prefix = ("season_betting_card_manifest_{0}_retuned_" -f $targetSeason); Suffix = '.json' },
    @{ Prefix = ("season_betting_card_day_{0}_retuned_" -f $targetSeason); Suffix = '.json' },
    @{ Prefix = ("season_betting_card_day_{0}_retuned_" -f $targetSeason); Suffix = '_insights.json' }
)

foreach ($artifact in $seasonBettingCardArtifacts) {
    $sourceDirectory = if ($UseExistingMirrorArtifacts) { $destDataRoot } elseif ($artifactRoot) { Join-Path $artifactRoot 'data\processed' } else { Join-Path $sourceRoot 'data\processed' }
    Copy-LatestDatedArtifact -SourceDirectory $sourceDirectory -DestinationDirectory $destDataRoot -Prefix $artifact.Prefix -Suffix $artifact.Suffix -TargetDate $targetDate | Out-Null
}

$datedLiveLensArtifacts = @(
    @{ Prefix = 'live_lens_projections_'; Suffix = '.jsonl' },
    @{ Prefix = 'live_lens_signals_'; Suffix = '.jsonl' }
)

foreach ($artifact in $datedLiveLensArtifacts) {
    $sourceDirectory = if ($UseExistingMirrorArtifacts) { $destLiveLensRoot } elseif ($artifactRoot) { Join-Path $artifactRoot 'data\live_lens' } else { Join-Path $sourceRoot 'data\live_lens' }
    Copy-LatestDatedArtifact -SourceDirectory $sourceDirectory -DestinationDirectory $destLiveLensRoot -Prefix $artifact.Prefix -Suffix $artifact.Suffix -TargetDate $targetDate -ManifestPrefix 'live_lens' | Out-Null
}

$liveLensStaticFiles = @(
    'live_lens_tuning_override.json'
)

foreach ($name in $liveLensStaticFiles) {
    $dst = Join-Path $destLiveLensRoot $name
    if (($UseExistingMirrorArtifacts -and (Test-Path $dst)) -or ((-not $UseExistingMirrorArtifacts) -and (Copy-IfExists -SourcePath (Join-Path ($(if ($artifactRoot) { $artifactRoot } else { $sourceRoot })) (Join-Path 'data\live_lens' $name)) -DestinationPath $dst))) {
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

foreach ($artifact in $datedLiveSnapshotArtifacts) {
    $sourceDirectory = if ($UseExistingMirrorArtifacts) { $destLiveSnapshotsRoot } elseif ($artifactRoot) { Join-Path $artifactRoot 'data\processed\live_snapshots' } else { Join-Path $sourceRoot 'data\processed\live_snapshots' }
    Copy-LatestDatedArtifact -SourceDirectory $sourceDirectory -DestinationDirectory $destLiveSnapshotsRoot -Prefix $artifact.Prefix -Suffix $artifact.Suffix -TargetDate $targetDate -ManifestPrefix 'live_snapshots' | Out-Null
}

$datedRawArtifacts = @(
    @{ Prefix = 'odds_nba_player_props_'; Suffix = '.csv' }
)

foreach ($artifact in $datedRawArtifacts) {
    $sourceDirectory = if ($UseExistingMirrorArtifacts) { $destRawRoot } elseif ($artifactRoot) { Join-Path $artifactRoot 'data\raw' } else { Join-Path $sourceRoot 'data\raw' }
    Copy-LatestDatedArtifact -SourceDirectory $sourceDirectory -DestinationDirectory $destRawRoot -Prefix $artifact.Prefix -Suffix $artifact.Suffix -TargetDate $targetDate -ManifestPrefix 'raw' | Out-Null
}

$webFiles = @(
    "betting-card-v2.css",
    "betting-card-v2.js"
)

foreach ($name in $webFiles) {
    $dst = Join-Path $destWebRoot $name
    if (($UseExistingMirrorArtifacts -and (Test-Path $dst)) -or ((-not $UseExistingMirrorArtifacts) -and (Copy-IfExists -SourcePath (Join-Path ($(if ($artifactRoot) { $artifactRoot } else { $sourceRoot })) (Join-Path 'web' $name)) -DestinationPath $dst))) {
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
    sourceArtifactRoot = $artifactRoot
    sourceRootEnvVar = $sourceRootEnvVar
    sourceArtifactRootEnvVar = $sourceArtifactRootEnvVar
    destinationRoot = (Join-Path $repoRoot 'data\nba_source')
    usedExistingMirrorArtifacts = [bool]$UseExistingMirrorArtifacts
    usedArtifactBundle = [bool](-not [string]::IsNullOrWhiteSpace($artifactRoot))
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