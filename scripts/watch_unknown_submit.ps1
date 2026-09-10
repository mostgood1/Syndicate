<#
.SYNOPSIS
    Unattended poll for Polymarket "unknown submit" rows and their balance_evidence.

.DESCRIPTION
    Replaces the Claude Code scheduled task `unknown-submit-balance-evidence-capture`
    for STEPS 1-3, which are purely mechanical: one unauthenticated GET, two counts,
    one appended heartbeat line. No model in the hot path.

    WHY THIS EXISTS. Measured 2026-08-31/09-01: 3 of the last 4 scheduled runs of the
    LLM task hung on the first Bash tool call -- transcript frozen at 1 tool_use with
    0 tool_result, curl.exe never spawned, no heartbeat written -- and a hung run
    BLOCKS every subsequent fire until its process is killed. Killing PID 16792 at
    23:57:53Z produced a fire at 00:10:44Z after 51 minutes of silence; that run then
    hung identically. Observed inter-fire spacing was 21m / 772m / 490m / 64m against
    a */15 schedule. The window this watches for is 16 MINUTES, so that is a dead
    watcher.

    READ-ONLY toward production. No credentials, no .env, no Render API, NO GIT.
    Writes exactly two local files, both inside the repo's .syndicate/ directory.

.NOTES
    Exit codes:
      0  ran, nothing found (the normal case)
      2  fetch failed after retries (heartbeat still written)
      3  payload unparseable      (heartbeat still written)
     10  AN UNKNOWN SUBMIT WAS CAPTURED -- a human should look, and should pull the
         matching UNKNOWN_ORDER_PROBE line from the worker logs while it is still in
         retention. Only the payload-side balance_evidence is captured here.
#>
[CmdletBinding()]
param(
    [string]$BaseUrl  = 'https://syndicate-an21.onrender.com/api/portfolio/live?on=all',
    [string]$RepoRoot = 'C:\Users\tempadmin\OneDrive\Coding\Syndicate',
    [int]$RecentWindowMinutes = 60
)

$ErrorActionPreference = 'Stop'

$synDir   = Join-Path $RepoRoot '.syndicate'
$hb       = Join-Path $synDir '.unknown_submit_watch_heartbeat'
$hbPrev   = "$hb.prev"
$findings = Join-Path $synDir 'findings_unknown_submit_live_evidence.md'

$nowUtc = [DateTime]::UtcNow
$stamp  = $nowUtc.ToString('yyyy-MM-ddTHH:mm:ssZ')
$today  = $nowUtc.ToString('yyyy-MM-dd')

# ---------- helpers ----------

# PS 5.1 ConvertFrom-Json yields PSCustomObject. Be explicit about absent keys
# rather than relying on $null-on-missing behaviour.
function Get-Prop($obj, [string]$name) {
    if ($null -eq $obj) { return $null }
    $p = $obj.PSObject.Properties[$name]
    if ($null -eq $p) { return $null }
    return $p.Value
}

# Add-Content -Encoding utf8 writes a BOM on file creation in PS 5.1, which would
# land inside the first heartbeat line and defeat the date regex below.
function Add-PlainText([string]$path, [string]$text) {
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::AppendAllText($path, $text, $enc)
}

# ONE UTC day per file, single-generation roll: today and yesterday, never more.
function Write-Heartbeat([string]$line) {
    if (Test-Path -LiteralPath $hb) {
        $first = ''
        try {
            $sr = New-Object System.IO.StreamReader($hb)
            $first = $sr.ReadLine()
            $sr.Close()
        } catch {
            $first = ''
        }
        if ($null -eq $first) { $first = '' }
        $m = [regex]::Match($first, '^(\d{4}-\d{2}-\d{2})')
        if ($m.Success -and ($m.Groups[1].Value -lt $today)) {
            if (Test-Path -LiteralPath $hbPrev) { Remove-Item -LiteralPath $hbPrev -Force }
            Move-Item -LiteralPath $hb -Destination $hbPrev -Force
        }
    }
    Add-PlainText $hb ($line + "`n")
}

if (-not (Test-Path -LiteralPath $synDir)) {
    Write-Error "No .syndicate directory at $synDir -- wrong RepoRoot?"
    exit 3
}

# ---------- STEP 1: one GET, retried ----------
# --retry 3 is what retries a 502 (curl already treats 5xx as transient).
# --retry-all-errors additionally covers connection-level refusal, which plain
# --retry abandons immediately. Measured on curl 8.14.1, re-confirmed on 8.21.0.
# Retries exhausted on a 502 STILL exit 0 with the code reported as 502, so read
# the -w code and never infer success from the exit status.

$tmp  = Join-Path $env:TEMP ('portfolio_live_{0}.json' -f ([guid]::NewGuid().ToString('N')))
$wfmt = 'HTTPCODE=%{http_code} RETRIES=%{num_retries} TIME=%{time_total}'

$meta = & curl.exe -s --max-time 90 --retry 3 --retry-delay 20 --retry-all-errors -w $wfmt -o $tmp $BaseUrl
$curlExit = $LASTEXITCODE

$code    = '000'
$retries = 0
$mm = [regex]::Match([string]$meta, 'HTTPCODE=(\d+)\s+RETRIES=(\d+)')
if ($mm.Success) {
    $code    = $mm.Groups[1].Value
    $retries = [int]$mm.Groups[2].Value
}

if ($code -ne '200') {
    Write-Heartbeat "$stamp ran=1 http=$code unknown_submits=0 recent_orders_60m=0 note=fetch_failed;retries=$retries;curl_exit=$curlExit"
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
    Write-Output "FETCH FAILED http=$code retries=$retries curl_exit=$curlExit"
    exit 2
}

try {
    $raw = Get-Content -LiteralPath $tmp -Raw -Encoding UTF8
    $d   = $raw | ConvertFrom-Json
} catch {
    Write-Heartbeat "$stamp ran=1 http=$code unknown_submits=0 recent_orders_60m=0 note=unparseable_payload;retries=$retries"
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
    Write-Output "PARSE FAILED"
    exit 3
}
if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }

$uRaw = Get-Prop $d 'unknown_submits'
if ($null -eq $uRaw) { $unknown = @() } else { $unknown = @($uRaw) }
$unknownDollars  = Get-Prop $d 'unknown_submit_dollars'
$unknownResolved = Get-Prop $d 'unknown_submits_resolved'

# ---------- STEP 3: the positive control ----------
# A null result only means something if the system is actually placing orders.
# recent=0 means the book was idle and the null says NOTHING about 5xx failures.
$recent    = 0
$ordersRaw = Get-Prop $d 'orders'
if ($null -ne $ordersRaw) {
    $cut = $nowUtc.AddMinutes(-$RecentWindowMinutes)
    foreach ($o in @($ordersRaw)) {
        $s = Get-Prop $o 'submitted_at'
        if ([string]::IsNullOrWhiteSpace([string]$s)) { continue }
        try {
            $dto = [DateTimeOffset]::Parse([string]$s,
                       [Globalization.CultureInfo]::InvariantCulture,
                       [Globalization.DateTimeStyles]::RoundtripKind)
        } catch {
            continue
        }
        if ($dto.UtcDateTime -ge $cut) { $recent++ }
    }
}

# ---------- STEP 2: heartbeat, every run ----------
$stateAge = Get-Prop $d 'state_age_seconds'
$by       = Get-Prop $d 'state_recorded_by'
if ($retries -gt 0) { $note = "recovered_after_${retries}_retries" } else { $note = 'clean' }
$note = "$note;state_age=${stateAge}s;by=$by;src=ps1"
Write-Heartbeat "$stamp ran=1 http=$code unknown_submits=$($unknown.Count) recent_orders_60m=$recent note=$note"

# ---------- STEP 4: capture, if there is anything to capture ----------
if ($unknown.Count -eq 0) {
    Write-Output "ok http=$code unknown=0 recent_orders_60m=$recent retries=$retries"
    exit 0
}

if (-not (Test-Path -LiteralPath $findings)) {
    $header  = "# Unknown-submit live evidence`n`n"
    $header += "First-hand captures of balance_evidence on Polymarket submits the venue never answered.`n"
    $header += "Written by scripts/watch_unknown_submit.ps1. Left UNCOMMITTED by design.`n"
    Add-PlainText $findings $header
}
$existing = Get-Content -LiteralPath $findings -Raw
if ($null -eq $existing) { $existing = '' }

$fence = '```'
$wrote = 0
foreach ($row in $unknown) {
    # Idempotence: runs are frequent and must not duplicate a row already recorded.
    $key = [string](Get-Prop $row 'idempotency_key')
    if (-not [string]::IsNullOrWhiteSpace($key) -and $existing.Contains($key)) { continue }

    $be      = Get-Prop $row 'balance_evidence'
    $verdict = Get-Prop $be 'verdict'
    $reason  = Get-Prop $be 'reason'

    if ($null -eq $be) {
        $reading = 'reading: NO balance_evidence object on this row'
    } elseif ([string]::IsNullOrWhiteSpace([string]$reason)) {
        $reading = "reading: $verdict"
    } else {
        # `unknown` IS a real result -- confounded is the guard refusing to guess.
        $reading = "reading: $verdict ($reason)"
    }

    $json = $row | ConvertTo-Json -Depth 12

    $block  = "`n## $stamp -- unknown submit captured`n`n"
    $block += "unknown_submit_dollars: $unknownDollars`n"
    $block += "unknown_submits_resolved: $unknownResolved`n"
    $block += "recent_orders_60m: $recent`n`n"
    $block += "${fence}json`n$json`n${fence}`n`n"
    $block += "$reading`n"
    Add-PlainText $findings $block

    $existing += $key
    $wrote++
}

Write-Output "CAPTURED $wrote of $($unknown.Count) unknown submit(s) -> $findings"
Write-Output "Pull the matching UNKNOWN_ORDER_PROBE line from the worker logs while it is still in retention."
if ($wrote -gt 0) { exit 10 }
exit 0
