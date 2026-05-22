param(
    [string]$Date = (Get-Date).ToString('yyyy-MM-dd'),
    [string]$SourceRepo = "..\NCAAFCompare"
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceRootEnvVar = 'SYNDICATE_SOURCE_ROOT_NCAAF'
$sourceRootCandidate = [Environment]::GetEnvironmentVariable($sourceRootEnvVar)
if ([string]::IsNullOrWhiteSpace($sourceRootCandidate)) {
    $sourceRootCandidate = Join-Path $repoRoot $SourceRepo
}
if (-not (Test-Path $sourceRootCandidate)) {
    throw "Source repo path not found: $sourceRootCandidate. Set $sourceRootEnvVar or pass -SourceRepo."
}
$sourceRoot = (Resolve-Path $sourceRootCandidate).Path
$sourceDataRoot = Join-Path $sourceRoot 'data'
$destRoot = Join-Path $repoRoot 'data\ncaaf_source\data'

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
    'recommendations_latest.json',
    'recommendations_2025.csv'
)

foreach ($name in $fileNames) {
    $src = Join-Path $sourceDataRoot $name
    $dst = Join-Path $destRoot $name
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst) {
        $copied.Add($name) | Out-Null
    }
}

$dirNames = @(
    'recommendations_summary'
)

foreach ($name in $dirNames) {
    $src = Join-Path $sourceDataRoot $name
    $dst = Join-Path $destRoot $name
    if (Copy-IfExists -SourcePath $src -DestinationPath $dst -Recurse) {
        $copied.Add($name) | Out-Null
    }
}

$artifactGroups = [ordered]@{
    recommendations = 0
    summaries = 0
    other = 0
}

foreach ($artifact in $copied) {
    if ($artifact -eq 'recommendations_summary') {
        $artifactGroups.summaries += 1
    }
    elseif ($artifact.StartsWith('recommendations_')) {
        $artifactGroups.recommendations += 1
    }
    else {
        $artifactGroups.other += 1
    }
}

$manifest = [pscustomobject]@{
    sport = 'ncaaf'
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

$manifestRoot = Join-Path $repoRoot 'data\ncaaf_source\manifests'
$manifestPath = Join-Path $manifestRoot ("mirror_refresh_{0}.json" -f $Date)
$latestManifestPath = Join-Path $manifestRoot 'mirror_refresh_latest.json'

Write-JsonFile -Path $manifestPath -Value $manifest
Write-JsonFile -Path $latestManifestPath -Value $manifest

$manifest | ConvertTo-Json -Depth 6