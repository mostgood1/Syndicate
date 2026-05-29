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
$sourceRootEnvVar = 'SYNDICATE_SOURCE_ROOT_WNBA'
$sourceArtifactRootEnvVar = 'SYNDICATE_ARTIFACT_ROOT_WNBA'

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
$destinationSportRoot = Resolve-DestinationSportRoot -LocalDirName 'wnba_source' -ExplicitRootEnvVars @('SYNDICATE_WNBA_SOURCE_ROOT')
$destDataRoot = Join-Path $destinationSportRoot 'data\processed'
$destRawRoot = Join-Path $destinationSportRoot 'data\raw'
$destLiveLensRoot = Join-Path $destinationSportRoot 'data\live_lens'

if (-not $UseExistingMirrorArtifacts) {
    $artifactRootCandidate = $SourceArtifactRoot
    if ([string]::IsNullOrWhiteSpace($artifactRootCandidate)) {
        $artifactRootCandidate = [Environment]::GetEnvironmentVariable($sourceArtifactRootEnvVar)
    }
    if (-not [string]::IsNullOrWhiteSpace($artifactRootCandidate)) {
        if (-not (Test-Path $artifactRootCandidate)) {
            throw "Artifact root path not found: $artifactRootCandidate. Set $sourceArtifactRootEnvVar or pass -SourceArtifactRoot with a published WNBA artifact bundle path."
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

function Copy-MatchingDatedArtifacts {
    param(
        [string]$SourceDirectory,
        [string]$DestinationDirectory,
        [string]$Prefix,
        [string]$Suffix,
        [datetime]$TargetDate
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

        if ($candidateDate -gt [datetime]::ParseExact($Date, 'yyyy-MM-dd', $null)) {
            continue
        }

        $destinationPath = Join-Path $DestinationDirectory $candidate.Name
        if (-not (Copy-IfExists -SourcePath $candidate.FullName -DestinationPath $destinationPath)) {
            continue
        }
        if (-not $copied.Contains($candidate.Name)) {
            $copied.Add($candidate.Name) | Out-Null
        }
        $copiedCount += 1
    }

    return $copiedCount
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
    "live_player_lens_tuning_$Date.csv",
    "boxscores_$Date.csv",
    "boxscores_history.csv",
    "live_lens_projections_$Date.jsonl",
    "live_lens_signals_$Date.jsonl",
    "live_lens_tuning_override.json"
)

foreach ($name in $files) {
    $dst = Join-Path $destDataRoot $name
    $src = if ($UseExistingMirrorArtifacts) { $dst } elseif ($artifactRoot) { Join-Path $artifactRoot (Join-Path 'data\processed' $name) } else { Join-Path $sourceRoot (Join-Path 'data\processed' $name) }
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst) {
        $copied.Add($name) | Out-Null
    }
}

$boxscoresSourceRoot = if ($UseExistingMirrorArtifacts) { $destDataRoot } elseif ($artifactRoot) { Join-Path $artifactRoot 'data\processed' } else { Join-Path $sourceRoot 'data\processed' }
Copy-MatchingDatedArtifacts -SourceDirectory $boxscoresSourceRoot -DestinationDirectory $destDataRoot -Prefix 'boxscores_' -Suffix '.csv' -TargetDate ([datetime]::ParseExact($Date, 'yyyy-MM-dd', $null)) | Out-Null

$smartSimSourceRoot = if ($UseExistingMirrorArtifacts) { $destDataRoot } elseif ($artifactRoot) { Join-Path $artifactRoot 'data\processed' } else { Join-Path $sourceRoot 'data\processed' }
if (Test-Path $smartSimSourceRoot) {
    foreach ($source in Get-ChildItem -Path $smartSimSourceRoot -Filter ("smart_sim_{0}_*.json" -f $Date) -File -ErrorAction SilentlyContinue) {
        $destination = Join-Path $destDataRoot $source.Name
        if (Copy-IfExists -SourcePath $source.FullName -DestinationPath $destination) {
            if (-not $copied.Contains($source.Name)) {
                $copied.Add($source.Name) | Out-Null
            }
        }
    }
}

$liveLensFiles = @(
    "live_lens_projections_$Date.jsonl",
    "live_lens_signals_$Date.jsonl",
    "live_lens_tuning_override.json"
)

foreach ($name in $liveLensFiles) {
    $dst = Join-Path $destLiveLensRoot $name
    $src = if ($UseExistingMirrorArtifacts) { $dst } elseif ($artifactRoot) { Join-Path $artifactRoot (Join-Path 'data\live_lens' $name) } else { Join-Path $sourceRoot (Join-Path 'data\live_lens' $name) }
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
    $src = if ($UseExistingMirrorArtifacts) { $dst } elseif ($artifactRoot) { Join-Path $artifactRoot (Join-Path 'data\raw' $name) } else { Join-Path $sourceRoot (Join-Path 'data\raw' $name) }
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