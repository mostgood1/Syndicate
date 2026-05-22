param(
    [string]$Date = (Get-Date).ToString('yyyy-MM-dd'),
    [string]$SourceRepo = "..\NFL-Betting"
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceRootEnvVar = 'SYNDICATE_SOURCE_ROOT_NFL'
$sourceRootCandidate = [Environment]::GetEnvironmentVariable($sourceRootEnvVar)
if ([string]::IsNullOrWhiteSpace($sourceRootCandidate)) {
    $sourceRootCandidate = Join-Path $repoRoot $SourceRepo
}
if (-not (Test-Path $sourceRootCandidate)) {
    throw "Source repo path not found: $sourceRootCandidate. Set $sourceRootEnvVar or pass -SourceRepo."
}
$sourceRoot = (Resolve-Path $sourceRootCandidate).Path
$sourceDataRoot = Join-Path $sourceRoot 'nfl_compare\data'
$destRoot = Join-Path $repoRoot 'data\nfl_source'

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

$fileNames = @(
    'current_week.json',
    'calibration_active.json',
    'prob_calibration.json',
    'sigma_calibration.json',
    'totals_calibration.json'
)

foreach ($name in $fileNames) {
    $src = Join-Path $sourceDataRoot $name
    $dst = Join-Path $destRoot $name
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst) {
        $copied.Add($name) | Out-Null
    }
}

Get-ChildItem -Path $sourceDataRoot -Filter 'upcoming_recs_*.csv' -File -ErrorAction SilentlyContinue | ForEach-Object {
    $dst = Join-Path $destRoot $_.Name
    if (Copy-IfExists -SourcePath $_.FullName -DestinationPath $dst) {
        $copied.Add($_.Name) | Out-Null
    }
}

Get-ChildItem -Path $sourceDataRoot -Filter 'real_betting_lines_*.json' -File -ErrorAction SilentlyContinue | ForEach-Object {
    $dst = Join-Path $destRoot $_.Name
    if (Copy-IfExists -SourcePath $_.FullName -DestinationPath $dst) {
        $copied.Add($_.Name) | Out-Null
    }
}

Get-ChildItem -Path $sourceDataRoot -Filter 'oddsapi_player_props_*.csv' -File -ErrorAction SilentlyContinue | ForEach-Object {
    $dst = Join-Path $destRoot $_.Name
    if (Copy-IfExists -SourcePath $_.FullName -DestinationPath $dst) {
        $copied.Add($_.Name) | Out-Null
    }
}

$dirNames = @(
    'manifests'
)

foreach ($name in $dirNames) {
    $src = Join-Path $sourceDataRoot $name
    $dst = Join-Path $destRoot $name
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst -Recurse) {
        $copied.Add($name) | Out-Null
    }
}

$artifactGroups = [ordered]@{
    calibration = 0
    recommendations = 0
    props = 0
    manifests = 0
    other = 0
}

foreach ($artifact in $copied) {
    if ($artifact -eq 'manifests') {
        $artifactGroups.manifests += 1
    }
    elseif ($artifact.StartsWith('upcoming_recs_') -or $artifact.StartsWith('real_betting_lines_')) {
        $artifactGroups.recommendations += 1
    }
    elseif ($artifact.StartsWith('oddsapi_player_props_')) {
        $artifactGroups.props += 1
    }
    elseif ($artifact -in @('current_week.json', 'calibration_active.json', 'prob_calibration.json', 'sigma_calibration.json', 'totals_calibration.json')) {
        $artifactGroups.calibration += 1
    }
    else {
        $artifactGroups.other += 1
    }
}

$manifest = [pscustomobject]@{
    sport = 'nfl'
    date = $Date
    refreshedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
    sourceRepo = $sourceRoot
    sourceRootEnvVar = $sourceRootEnvVar
    sourceDataRoot = $sourceDataRoot
    destinationRoot = $destRoot
    copiedArtifactCount = $copied.Count
    artifactGroups = [pscustomobject]$artifactGroups
    copiedArtifacts = @($copied)
}

$manifestRoot = Join-Path $repoRoot 'data\nfl_source\manifests'
$manifestPath = Join-Path $manifestRoot ("mirror_refresh_{0}.json" -f $Date)
$latestManifestPath = Join-Path $manifestRoot 'mirror_refresh_latest.json'

Write-JsonFile -Path $manifestPath -Value $manifest
Write-JsonFile -Path $latestManifestPath -Value $manifest

$manifest | ConvertTo-Json -Depth 6