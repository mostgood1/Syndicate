param(
    [string]$Date = (Get-Date).ToString('yyyy-MM-dd'),
    [string]$BaseUrl,
    [switch]$Json,
    [switch]$SkipTests,
    [switch]$SkipSmoke,
    [switch]$SkipGitPush,
    [switch]$DryRun,
    [switch]$IncludeOffSeasonSports,
    [switch]$ForceMLB,
    [switch]$ForceNBA,
    [switch]$ForceNHL,
    [switch]$ForceWNBA,
    [switch]$ForceNFL,
    [switch]$ForceNCAAF,
    [switch]$ForceNCAAB
)

$ErrorActionPreference = 'Stop'

$target = Join-Path $PSScriptRoot 'scripts\daily_update_in_season.ps1'
if (-not (Test-Path -LiteralPath $target)) {
    throw "Could not find target script: $target"
}

& $target @PSBoundParameters