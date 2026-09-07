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

    IT DOES NOT READ THE PRIMARY CHECKOUT'S CONTENT. It reports on `origin/main`,
    via a small reusable sparse worktree holding only `scripts/` and `vendor/`.

    That is not tidiness, it is the first thing that broke. The first registered
    run failed outright: the primary checkout is **241 commits behind
    origin/main** and does not contain `scripts/sync_vendor_upstream.py` at all,
    because that script landed today. A daily job pinned to a shared working tree
    inherits whatever state that tree happens to be in -- which here is months of
    drift plus other sessions' uncommitted work. `origin/main` is the thing worth
    reporting on anyway: it is what a sync would be applied to.

    The primary checkout's own lag is still recorded, as `primary_behind_origin_main`,
    because it is worth knowing and costs one command.

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

# Run a native command and judge it by its EXIT CODE, never by whether it wrote
# to stderr.
#
# This is not defensive style, it is the second thing that broke here. Windows
# PowerShell 5.1 wraps each stderr line from a native exe in an ErrorRecord when
# that stream is redirected, so with `$ErrorActionPreference = 'Stop'` git's
# ordinary chatter throws. The first attempt recorded
# `error: "Preparing worktree (detached HEAD aa0349aa)"` -- git's own progress
# message, on a command that had SUCCEEDED -- and reported the run as failed.
function Invoke-Native {
    # NOT `$Args`: that is a PowerShell AUTOMATIC variable holding a function's
    # unbound arguments, and a parameter of that name does not bind reliably --
    # the failure looked like `git  -> exit 1`, git invoked with no arguments.
    param([string] $Exe, [string[]] $Arguments, [switch] $Capture)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($Capture) { $out = & $Exe @Arguments } else { & $Exe @Arguments | Out-Null; $out = $null }
        if ($LASTEXITCODE -ne 0) { throw ("{0} {1} -> exit {2}" -f $Exe, ($Arguments -join " "), $LASTEXITCODE) }
        return $out
    } finally { $ErrorActionPreference = $prev }
}

$behind = $null
$syncedRef = $null
$syncJson = $null
$syncError = $null

try {
    Invoke-Native git @("-C", $RepoRoot, "fetch", "--quiet", "origin", "main")

    # Informational only. Never corrected here: moving somebody else's shared
    # working tree is not this job's business.
    $behind = (Invoke-Native git @("-C", $RepoRoot, "rev-list", "--count", "HEAD..origin/main") -Capture | Select-Object -First 1)
    $syncedRef = (Invoke-Native git @("-C", $RepoRoot, "rev-parse", "--short", "origin/main") -Capture | Select-Object -First 1)

    # A small reusable worktree at origin/main, holding only what the sync reads.
    # Created once, re-pointed each run. Sparse because a full worktree of this
    # repo is 37k files and `data/` alone is 34k of them.
    $wt = Join-Path $env:LOCALAPPDATA "syndicate\vendor-sync-worktree"
    if (-not (Test-Path (Join-Path $wt ".git"))) {
        if (Test-Path $wt) { Remove-Item -Recurse -Force $wt }
        New-Item -ItemType Directory -Path (Split-Path -Parent $wt) -Force | Out-Null
        Invoke-Native git @("-C", $RepoRoot, "worktree", "add", "--detach", "--no-checkout", $wt, "origin/main")
    }

    # CHECK THE POSTCONDITION, do not infer it from "the directory exists".
    # A run that dies between `worktree add` and `sparse-checkout set` leaves a
    # worktree that is real but NOT sparse, and an existence check calls that
    # done -- after which every checkout materialises the whole repo. That
    # happened: the first attempt threw on git's stderr (see Invoke-Native), and
    # the leftover worktree grew to 3.9 GB, `data/` and all, on a job whose input
    # is two directories.
    $isSparse = $false
    try {
        $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        & git -C $wt sparse-checkout list 2>&1 | Out-Null
        $isSparse = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = $prev
    } catch { $isSparse = $false }
    if (-not $isSparse) {
        Invoke-Native git @("-C", $wt, "sparse-checkout", "set", "scripts", "vendor")
    }

    Invoke-Native git @("-C", $wt, "checkout", "--detach", "--force", "origin/main")

    $script = Join-Path $wt "scripts\sync_vendor_upstream.py"
    if (-not (Test-Path $script)) { throw "sync script absent at origin/main: $script" }

    # The sync exits 1 when files need a decision -- a normal, expected outcome,
    # not a failure. Its JSON is the result; judge that, not the code.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $raw = & py -3 $script --json
    $ErrorActionPreference = $prev
    if (-not $raw) { throw "sync produced no output" }
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
    primary_head       = (& git -C $RepoRoot rev-parse --short HEAD 2>$null | Select-Object -First 1)
    synced_ref         = $syncedRef
    primary_behind_origin_main = if ($null -ne $behind) { [int]$behind } else { $null }
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
    primary_behind_origin_main = $record.primary_behind_origin_main
    actionable         = $actionable.Count
    totals             = $totals
} | ConvertTo-Json -Depth 4 -Compress
[System.IO.File]::AppendAllText((Join-Path $outDir "history.jsonl"), $row + "`n", [System.Text.UTF8Encoding]::new($false))

if (-not $record.ok) {
    Write-Output "vendor-sync report FAILED: $syncError"
    exit 1
}

$summary = ($totals.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key) $($_.Value)" }) -join ", "
Write-Output "vendor-sync $started  [$summary]  actionable=$($actionable.Count)  synced_ref=$($record.synced_ref) primary_behind=$($record.primary_behind_origin_main)"
foreach ($a in $actionable) { Write-Output "  $($a.state)  $($a.tree)/$($a.path)" }
exit 0
