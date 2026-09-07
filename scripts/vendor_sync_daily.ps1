<#
.SYNOPSIS
    Daily vendor-sync REPORT, written as an artifact that proves it executed.

.DESCRIPTION
    A stopgap for `.github/workflows/vendor-sync.yml`, which is correct but cannot
    run: GitHub Actions is billing-locked for this account (no successful run in
    this repo since 2026-08-22).

    THE ARTIFACT IS THE POINT, not the exit code. This machine's ledger records a
    scheduled call being stalled 9h13m by Modern Standby, with the scheduler's own
    `LastRunTime` reporting the DISPATCH rather than the execution -- and the
    Actions workflow failed the same silent way, never starting and therefore
    never reporting. For a job whose output is "nothing changed upstream", not
    running is indistinguishable from running and finding nothing. So every run
    stamps `executed_at` into `reports/vendor_sync/latest.json` and appends a row
    to `history.jsonl`. Trust those; do not trust `Get-ScheduledTaskInfo`.

    REPORT ONLY. It never writes `vendor/`. The primary checkout is shared by
    concurrent sessions, and leaving modified vendored files lying in it is how an
    unrelated session sweeps them into its commit. Applying an upstream change
    stays a human act -- run `scripts/sync_vendor_upstream.py --apply` yourself.

    It also records how far behind `origin/main` this checkout is. The primary
    tree is routinely behind, and a sync reading a stale tree can classify an
    already-resolved file as UNCLASSIFIED. A labelled reading beats a wrong one.

.PARAMETER RepoRoot
    Checkout to report on. Defaults to this script's own repository.

.PARAMETER Register
    Register (or re-register) the daily scheduled task instead of running.

.PARAMETER Time
    Local time of day for -Register. Default 09:20.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\vendor_sync_daily.ps1
    powershell -ExecutionPolicy Bypass -File scripts\vendor_sync_daily.ps1 -Register
#>
[CmdletBinding()]
param(
    [string] $RepoRoot,
    [switch] $Register,
    [string] $Time = "09:20"
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$TaskName = "Syndicate vendor-sync report"

function Register-Task {
    $script = Join-Path $RepoRoot "scripts\vendor_sync_daily.ps1"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument ("-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"{0}`" -RepoRoot `"{1}`"" -f $script, $RepoRoot)
    $trigger = New-ScheduledTaskTrigger -Daily -At $Time

    # StartWhenAvailable is the whole reason this is worth registering at all:
    # without it a missed window is simply skipped, which on a laptop that sleeps
    # is most windows. It does NOT make the run punctual -- it makes it happen.
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
        -MultipleInstances IgnoreNew

    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Description "Daily vendor-sync report. Stopgap while GitHub Actions is billing-locked. Reads reports/vendor_sync/latest.json for proof of execution." `
        -Force | Out-Null

    Write-Output "registered: $TaskName  daily at $Time"
    Write-Output "  runs: $script"
    Write-Output "  VERIFY BY THE ARTIFACT, not by LastRunTime:"
    Write-Output "    reports/vendor_sync/latest.json -> executed_at"
    exit 0
}

if ($Register) { Register-Task }

# --- run the report ---------------------------------------------------------

$outDir = Join-Path $RepoRoot "reports\vendor_sync"
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }

$started = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

# How stale is this checkout? Recorded, not corrected -- fetching is cheap, but
# moving someone else's shared working tree is not this job's business.
$behind = $null
try {
    & git -C $RepoRoot fetch --quiet origin main 2>$null
    $behind = (& git -C $RepoRoot rev-list --count "HEAD..origin/main" 2>$null | Select-Object -First 1)
} catch { $behind = $null }

$syncJson = $null
$syncError = $null
try {
    $raw = & py -3 (Join-Path $RepoRoot "scripts\sync_vendor_upstream.py") --json 2>$null
    $syncJson = ($raw -join "`n") | ConvertFrom-Json
} catch {
    $syncError = $_.Exception.Message
}

$totals = @{}
$actionable = @()
if ($null -ne $syncJson) {
    foreach ($p in $syncJson.totals.PSObject.Properties) { $totals[$p.Name] = $p.Value }
    foreach ($tree in $syncJson.trees) {
        foreach ($row in $tree.rows) {
            if ($row.state -in @("UPSTREAM_AHEAD", "CONFLICT", "UNCLASSIFIED")) {
                $actionable += [ordered]@{ tree = $tree.tree; path = $row.path; state = $row.state }
            }
        }
    }
}

$record = [ordered]@{
    executed_at        = $started
    finished_at        = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    host               = $env:COMPUTERNAME
    repo_root          = $RepoRoot
    head               = (& git -C $RepoRoot rev-parse --short HEAD 2>$null | Select-Object -First 1)
    behind_origin_main = if ($null -ne $behind) { [int]$behind } else { $null }
    ok                 = ($null -ne $syncJson)
    error              = $syncError
    totals             = $totals
    actionable_count   = $actionable.Count
    actionable         = $actionable
}

$json = $record | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText((Join-Path $outDir "latest.json"), $json + "`n", [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::WriteAllText((Join-Path $outDir ($started.Substring(0,10) + ".json")), $json + "`n", [System.Text.UTF8Encoding]::new($false))

# One line per run, so a GAP in this file is the signal that the task did not
# fire -- which is the failure this whole design exists to make visible.
$row = [ordered]@{
    executed_at        = $started
    ok                 = $record.ok
    behind_origin_main = $record.behind_origin_main
    actionable         = $actionable.Count
    totals             = $totals
} | ConvertTo-Json -Depth 4 -Compress
[System.IO.File]::AppendAllText((Join-Path $outDir "history.jsonl"), $row + "`n", [System.Text.UTF8Encoding]::new($false))

if (-not $record.ok) {
    Write-Output "vendor-sync report FAILED: $syncError"
    exit 1
}

$summary = ($totals.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key) $($_.Value)" }) -join ", "
Write-Output "vendor-sync $started  [$summary]  actionable=$($actionable.Count)  behind_origin_main=$($record.behind_origin_main)"
foreach ($a in $actionable) { Write-Output "  $($a.state)  $($a.tree)/$($a.path)" }
exit 0
