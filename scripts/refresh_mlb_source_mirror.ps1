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
$sourceRootEnvVar = 'SYNDICATE_SOURCE_ROOT_MLB'
$sourceArtifactRootEnvVar = 'SYNDICATE_ARTIFACT_ROOT_MLB'
$sourceRoot = $null
$artifactRoot = $null
$localSourceRoot = Join-Path $repoRoot 'data\mlb_source'
$localArtifactRoot = Join-Path $localSourceRoot 'source_artifacts'
$destDataRoot = Join-Path $repoRoot 'data\mlb_source\data'
$dateSlug = $Date -replace '-', '_'
$season = ($Date -split '-')[0]
$seasonPayloadSlug = $dateSlug
if ($seasonPayloadSlug.StartsWith("$season`_")) {
    $seasonPayloadSlug = $seasonPayloadSlug.Substring($season.Length + 1)
}

if (-not $UseExistingMirrorArtifacts) {
    $artifactRootCandidate = $SourceArtifactRoot
    if ([string]::IsNullOrWhiteSpace($artifactRootCandidate)) {
        $artifactRootCandidate = [Environment]::GetEnvironmentVariable($sourceArtifactRootEnvVar)
    }
    if ([string]::IsNullOrWhiteSpace($artifactRootCandidate) -and (Test-Path $localArtifactRoot)) {
        $artifactRootCandidate = $localArtifactRoot
    }
    if (-not [string]::IsNullOrWhiteSpace($artifactRootCandidate)) {
        if (-not (Test-Path $artifactRootCandidate)) {
            throw "Artifact root path not found: $artifactRootCandidate. Set $sourceArtifactRootEnvVar or pass -SourceArtifactRoot with a published MLB artifact bundle path."
        }
        $artifactRoot = (Resolve-Path $artifactRootCandidate).Path
    }
}

if ((-not $UseExistingMirrorArtifacts) -and (-not $artifactRoot)) {
    $sourceRootCandidate = [Environment]::GetEnvironmentVariable($sourceRootEnvVar)
    if ([string]::IsNullOrWhiteSpace($sourceRootCandidate)) {
        if (Test-Path $localSourceRoot) {
            $sourceRootCandidate = $localSourceRoot
        }
    }
    if ([string]::IsNullOrWhiteSpace($sourceRootCandidate)) {
        $sourceRootCandidate = Join-Path $repoRoot $SourceRepo
    }
    if (-not (Test-Path $sourceRootCandidate)) {
        throw "Source path not found: $sourceRootCandidate. Set $sourceRootEnvVar, pass -SourceRepo, set $sourceArtifactRootEnvVar / -SourceArtifactRoot, or use -UseExistingMirrorArtifacts."
    }
    $sourceRoot = (Resolve-Path $sourceRootCandidate).Path
}

function Copy-IfExists {
    param(
        [string]$SourcePath,
        [string]$DestinationPath,
        [switch]$Recurse
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

    if ($Recurse) {
        if (Test-Path $DestinationPath) {
            Remove-Item -Path $DestinationPath -Recurse -Force
        }
        Copy-Item -Path $SourcePath -Destination $DestinationPath -Recurse -Force
    }
    else {
        Copy-Item -Path $SourcePath -Destination $DestinationPath -Force
    }

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

$filePairs = @(
    @("data\daily\lineups_last_known_by_team.json", "daily\lineups_last_known_by_team.json"),
    @("data\daily\daily_summary_$dateSlug.json", "daily\daily_summary_$dateSlug.json"),
    @("data\daily\daily_summary_${dateSlug}_profile_bundle.json", "daily\daily_summary_${dateSlug}_profile_bundle.json"),
    @("data\daily\daily_summary_${dateSlug}_locked_policy.json", "daily\daily_summary_${dateSlug}_locked_policy.json"),
    @("data\daily\daily_summary_${dateSlug}_hr_targets.json", "daily\daily_summary_${dateSlug}_hr_targets.json"),
    @("data\daily\daily_summary_${dateSlug}_rfi_targets.json", "daily\daily_summary_${dateSlug}_rfi_targets.json"),
    @("data\manager\manager_tendencies.json", "manager\manager_tendencies.json"),
    @("data\manager\probable_pitcher_overrides.json", "manager\probable_pitcher_overrides.json"),
    @("data\park\park_factors.json", "park\park_factors.json"),
    @("data\umpire\umpire_factors.json", "umpire\umpire_factors.json"),
    @("data\umpire\umpire_factors_report_2025-07-01_2025-09-30.json", "umpire\umpire_factors_report_2025-07-01_2025-09-30.json"),
    @("data\daily\ladders\daily_ladders_$dateSlug.json", "daily\ladders\daily_ladders_$dateSlug.json"),
    @("data\daily\top_props\daily_top_props_$dateSlug.json", "daily\top_props\daily_top_props_$dateSlug.json"),
    @("data\daily\ops\daily_ops_$dateSlug.json", "daily\ops\daily_ops_$dateSlug.json"),
    @("data\daily\season_frontend\season_betting_day_$dateSlug.json", "daily\season_frontend\season_betting_day_$dateSlug.json"),
    @("data\live_lens\live_lens_$dateSlug.jsonl", "live_lens\live_lens_$dateSlug.jsonl"),
    @("data\live_lens\live_lens_report_$dateSlug.json", "live_lens\live_lens_report_$dateSlug.json"),
    @("data\live_lens\prop_registry\live_prop_registry_$dateSlug.json", "live_lens\prop_registry\live_prop_registry_$dateSlug.json"),
    @("data\live_lens\prop_registry\live_prop_registry_$dateSlug.jsonl", "live_lens\prop_registry\live_prop_registry_$dateSlug.jsonl"),
    @("data\live_lens\prop_registry\live_prop_observations_$dateSlug.jsonl", "live_lens\prop_registry\live_prop_observations_$dateSlug.jsonl"),
    @("data\tuning\live_prop_ranking\default.json", "tuning\live_prop_ranking\default.json"),
    @("sim_engine\live_prop_ranking.py", "..\sim_engine\live_prop_ranking.py")
)

foreach ($pair in $filePairs) {
    $dst = Join-Path $destDataRoot $pair[1]
    $src = if ($UseExistingMirrorArtifacts) { $dst } elseif ($artifactRoot) { Join-Path $artifactRoot $pair[0] } else { Join-Path $sourceRoot $pair[0] }
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst) {
        $copied.Add($pair[1]) | Out-Null
    }
}

$dirPairs = @(
    @("data\cache", "cache"),
    @("data\daily_hitter_props", "daily_hitter_props"),
    @("data\daily_pitcher_props", "daily_pitcher_props"),
    @("data\daily\snapshots\$Date", "daily\snapshots\$Date"),
    @("data\daily\sims\$Date", "daily\sims\$Date"),
    @("data\manager", "manager"),
    @("data\park", "park"),
    @("data\market\oddsapi\refresh_history\$dateSlug", "market\oddsapi\refresh_history\$dateSlug"),
    @("data\raw\statcast\pitches", "raw\statcast\pitches"),
    @("data\raw\statsapi\feed_live", "raw\statsapi\feed_live"),
    @("data\roster_registry", "roster_registry"),
    @("data\runtime", "runtime"),
    @("data\statcast", "statcast"),
    @("data\umpire", "umpire"),
    @("data\raw\statsapi\feed_live\$season\$Date", "raw\statsapi\feed_live\$season\$Date")
)

foreach ($pair in $dirPairs) {
    $dst = Join-Path $destDataRoot $pair[1]
    $src = if ($UseExistingMirrorArtifacts) { $dst } elseif ($artifactRoot) { Join-Path $artifactRoot $pair[0] } else { Join-Path $sourceRoot $pair[0] }
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst -Recurse) {
        $copied.Add($pair[1]) | Out-Null
    }
}

$seasonEvalRoot = if ($UseExistingMirrorArtifacts) { Join-Path $destDataRoot (Join-Path 'eval\seasons' $season) } elseif ($artifactRoot) { Join-Path $artifactRoot (Join-Path 'data\eval\seasons' $season) } else { Join-Path $sourceRoot (Join-Path 'data\eval\seasons' $season) }
$seasonEvalManifest = Join-Path $seasonEvalRoot 'season_eval_manifest.json'
if (Copy-IfExists -SourcePath $seasonEvalManifest -DestinationPath (Join-Path $destDataRoot (Join-Path 'eval\seasons' (Join-Path $season 'season_eval_manifest.json')))) {
    $copied.Add((Join-Path 'eval\seasons' (Join-Path $season 'season_eval_manifest.json'))) | Out-Null
}

$seasonManifestFiles = @(
    'season_betting_cards_retuned_manifest.json',
    'season_betting_cards_retuned_hrr_manifest.json'
)

foreach ($name in $seasonManifestFiles) {
    $src = Join-Path $seasonEvalRoot $name
    $relative = Join-Path 'eval\seasons' (Join-Path $season $name)
    $dst = Join-Path $destDataRoot $relative
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst) {
        $copied.Add($relative) | Out-Null
    }
}

if (Test-Path $seasonEvalRoot) {
    Get-ChildItem -Path $seasonEvalRoot -Directory -Filter 'betting_day_payloads*' -ErrorAction SilentlyContinue | ForEach-Object {
        $payloadDir = $_
        Get-ChildItem -Path $payloadDir.FullName -File -Filter ("season_betting_day_{0}_{1}*.json" -f $season, $seasonPayloadSlug) -ErrorAction SilentlyContinue | ForEach-Object {
            $relative = Join-Path 'eval\seasons' (Join-Path $season (Join-Path $payloadDir.Name $_.Name))
            $dst = Join-Path $destDataRoot $relative
            if (Copy-IfExists -SourcePath $_.FullName -DestinationPath $dst) {
                $copied.Add($relative) | Out-Null
            }
        }
    }

    Get-ChildItem -Path $seasonEvalRoot -Directory -Filter 'betting_day_recaps*' -ErrorAction SilentlyContinue | ForEach-Object {
        $recapDir = $_
        Get-ChildItem -Path $recapDir.FullName -File -Filter ("season_betting_day_{0}_{1}*.json" -f $season, $seasonPayloadSlug) -ErrorAction SilentlyContinue | ForEach-Object {
            $relative = Join-Path 'eval\seasons' (Join-Path $season (Join-Path $recapDir.Name $_.Name))
            $dst = Join-Path $destDataRoot $relative
            if (Copy-IfExists -SourcePath $_.FullName -DestinationPath $dst) {
                $copied.Add($relative) | Out-Null
            }
        }
    }
}

$liveLensRecapSource = if ($UseExistingMirrorArtifacts) { Join-Path $destDataRoot (Join-Path 'live_lens\recaps' ("live_lens_daily_recap_{0}.json" -f $dateSlug)) } elseif ($artifactRoot) { Join-Path $artifactRoot (Join-Path 'data\live_lens\recaps' ("live_lens_daily_recap_{0}.json" -f $dateSlug)) } else { Join-Path $sourceRoot (Join-Path 'data\live_lens\recaps' ("live_lens_daily_recap_{0}.json" -f $dateSlug)) }
$liveLensRecapDest = Join-Path $destDataRoot (Join-Path 'live_lens\recaps' ("live_lens_daily_recap_{0}.json" -f $dateSlug))
if (Copy-IfExists -SourcePath $liveLensRecapSource -DestinationPath $liveLensRecapDest) {
    $copied.Add((Join-Path 'live_lens\recaps' ("live_lens_daily_recap_{0}.json" -f $dateSlug))) | Out-Null
}

$artifactGroups = [ordered]@{
    daily = 0
    eval = 0
    live_lens = 0
    market = 0
    raw = 0
    other = 0
}

foreach ($artifact in $copied) {
    if ($artifact.StartsWith('daily\')) {
        $artifactGroups.daily += 1
    }
    elseif ($artifact.StartsWith('eval\')) {
        $artifactGroups.eval += 1
    }
    elseif ($artifact.StartsWith('live_lens\')) {
        $artifactGroups.live_lens += 1
    }
    elseif ($artifact.StartsWith('market\')) {
        $artifactGroups.market += 1
    }
    elseif ($artifact.StartsWith('raw\')) {
        $artifactGroups.raw += 1
    }
    else {
        $artifactGroups.other += 1
    }
}

$manifest = [pscustomobject]@{
    sport = 'mlb'
    date = $Date
    refreshedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
    sourceRepo = $sourceRoot
    sourceArtifactRoot = $artifactRoot
    sourceRootEnvVar = $sourceRootEnvVar
    sourceArtifactRootEnvVar = $sourceArtifactRootEnvVar
    destinationRoot = $destDataRoot
    usedExistingMirrorArtifacts = [bool]$UseExistingMirrorArtifacts
    usedArtifactBundle = [bool](-not [string]::IsNullOrWhiteSpace($artifactRoot))
    copiedArtifactCount = $copied.Count
    artifactGroups = [pscustomobject]$artifactGroups
    copiedArtifacts = @($copied)
}

$manifestRoot = Join-Path $repoRoot 'data\mlb_source\manifests'
$manifestPath = Join-Path $manifestRoot ("mirror_refresh_{0}.json" -f $Date)
$latestManifestPath = Join-Path $manifestRoot 'mirror_refresh_latest.json'

Write-JsonFile -Path $manifestPath -Value $manifest
Write-JsonFile -Path $latestManifestPath -Value $manifest

$manifest | ConvertTo-Json -Depth 6