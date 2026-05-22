param(
    [string]$Date = (Get-Date).ToString('yyyy-MM-dd'),
    [string]$SourceRepo = "..\NCAAB",
    [switch]$UseExistingRawOutputs
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$destRoot = Join-Path $repoRoot 'data\ncaab_source'
$destApiRoot = Join-Path $destRoot 'api'
$manifestRoot = Join-Path $destRoot 'manifests'
$rawOutputsRoot = Join-Path $destRoot 'raw_outputs'
$sourceRootEnvVar = 'SYNDICATE_SOURCE_ROOT_NCAAB'
$sourceRoot = $null
$sourcePython = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'py' }

if (-not $UseExistingRawOutputs) {
    $sourceRootCandidate = [Environment]::GetEnvironmentVariable($sourceRootEnvVar)
    if ([string]::IsNullOrWhiteSpace($sourceRootCandidate)) {
        $sourceRootCandidate = Join-Path $repoRoot $SourceRepo
    }
    if (-not (Test-Path $sourceRootCandidate)) {
        throw "Source repo path not found: $sourceRootCandidate. Set $sourceRootEnvVar, pass -SourceRepo, or use -UseExistingRawOutputs."
    }
    $sourceRoot = (Resolve-Path $sourceRootCandidate).Path
    $sourcePythonCandidate = Join-Path $sourceRoot '.venv\Scripts\python.exe'
    if (Test-Path $sourcePythonCandidate) {
        $sourcePython = $sourcePythonCandidate
    }
} elseif (-not (Test-Path $rawOutputsRoot)) {
    throw "Existing raw outputs not found: $rawOutputsRoot. Run a source-backed refresh first or omit -UseExistingRawOutputs."
}

New-Item -ItemType Directory -Path $destApiRoot -Force | Out-Null
New-Item -ItemType Directory -Path $manifestRoot -Force | Out-Null

$exportScriptPath = Join-Path $repoRoot 'scripts\export_ncaab_source_mirror.py'
$exportArgs = @($exportScriptPath, $destApiRoot, $Date)
if ($UseExistingRawOutputs) {
    $exportArgs += @('--raw-root', $rawOutputsRoot)
} else {
    $exportArgs += @('--source-root', $sourceRoot)
}
& $sourcePython @exportArgs
if ($LASTEXITCODE -ne 0) {
    throw "NCAAB source export failed with exit code $LASTEXITCODE"
}

$apiManifestPath = Join-Path $destApiRoot 'manifest.json'
$rawOutputsManifestPath = Join-Path $destRoot 'raw_outputs\manifest.json'

if (-not (Test-Path $apiManifestPath)) {
    throw "Expected NCAAB api manifest was not written: $apiManifestPath"
}

$apiManifest = Get-Content -Path $apiManifestPath -Raw -Encoding utf8 | ConvertFrom-Json
$rawOutputsManifest = if (Test-Path $rawOutputsManifestPath) {
    Get-Content -Path $rawOutputsManifestPath -Raw -Encoding utf8 | ConvertFrom-Json
} else {
    $null
}

$copiedArtifacts = New-Object System.Collections.Generic.List[string]
foreach ($artifact in @($apiManifest.copied_artifacts)) {
    if ($artifact) {
        $copiedArtifacts.Add([string]$artifact) | Out-Null
    }
}
foreach ($artifact in @($rawOutputsManifest.config_files)) {
    if ($artifact) {
        $copiedArtifacts.Add([string]$artifact) | Out-Null
    }
}
foreach ($artifact in @($rawOutputsManifest.date_files)) {
    if ($artifact) {
        $copiedArtifacts.Add([string]$artifact) | Out-Null
    }
}

$artifactGroups = [ordered]@{
    api = @($apiManifest.copied_artifacts).Count
    raw_outputs_config = @($rawOutputsManifest.config_files).Count
    raw_outputs_date = @($rawOutputsManifest.date_files).Count
    other = 0
}

$mirrorManifest = [pscustomobject]@{
    sport = 'ncaab'
    date = $Date
    refreshedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
    sourceRepo = $sourceRoot
    sourceRootEnvVar = $sourceRootEnvVar
    destinationRoot = $destRoot
    usedExistingRawOutputs = [bool]$UseExistingRawOutputs
    copiedArtifactCount = $copiedArtifacts.Count
    artifactGroups = [pscustomobject]$artifactGroups
    copiedArtifacts = @($copiedArtifacts)
}

$manifestPath = Join-Path $manifestRoot ("mirror_refresh_{0}.json" -f $Date)
$latestManifestPath = Join-Path $manifestRoot 'mirror_refresh_latest.json'

$mirrorManifest | ConvertTo-Json -Depth 6 | Set-Content -Path $manifestPath -Encoding utf8
$mirrorManifest | ConvertTo-Json -Depth 6 | Set-Content -Path $latestManifestPath -Encoding utf8

$mirrorManifest | ConvertTo-Json -Depth 6