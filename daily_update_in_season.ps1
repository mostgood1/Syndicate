param(
    [string]$Date,
    [string]$BaseUrl,
    [switch]$Json,
    [switch]$RefreshOdds,
    [string]$OddsPhase = 'all',
    [string]$OddsSports = 'all',
    [string]$OddsRegions = 'us',
    [int]$EventSimForceWindowMinutes = 30,
    [switch]$SkipTests,
    [switch]$SkipSmoke,
    [switch]$SkipSourceUpdates,
    [switch]$SkipRefreshGate,
    [switch]$RunGateTests,
    [switch]$RunGateSmoke,
    [switch]$SkipGitPush,
    [switch]$DryRun,
    [switch]$IncludeOffSeasonSports,
    [switch]$ForceRebuildToday,
    [switch]$ForceMLB,
    [switch]$ForceNBA,
    [switch]$ForceNHL,
    [switch]$ForceWNBA,
    [switch]$ForceNFL,
    [switch]$ForceNCAAF,
    [switch]$ForceNCAAB
)

$ErrorActionPreference = 'Stop'

# Use Central Time for date calculations to match Syndicate's timezone
if ([string]::IsNullOrWhiteSpace($Date)) {
    $centralTZ = [TimeZoneInfo]::FindSystemTimeZoneById("Central Standard Time")
    $Date = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $centralTZ).ToString('yyyy-MM-dd')
}

$target = Join-Path $PSScriptRoot 'scripts\daily_update_in_season.ps1'
if (-not (Test-Path -LiteralPath $target)) {
    throw "Could not find target script: $target"
}

& $target @PSBoundParameters