<#
Windows side of the local production health watchdog. Lane `local-prod-watchdog` [2026-10-02].
Runs `scripts/local_watchdog.py --json` inside WSL and turns its `alert` into a Windows
notification. Also alerts when WSL does not answer at all -- the one failure the
WSL-side check cannot report about itself.

Normally run every 5 minutes by the task `install_watchdog_task.ps1` registers.

  powershell -NoProfile -ExecutionPolicy Bypass -File watchdog.ps1              # one check
  powershell -NoProfile -ExecutionPolicy Bypass -File watchdog.ps1 -TestToast   # prove notifications show

Windows-side state and a one-line-per-run log live in -StateDir (default C:\SyndicateProd\watchdog).
#>
param(
    [string] $WslDistro = 'Ubuntu-24.04',
    [string] $WslRepo = '~/Syndicate',
    [string] $WslPython = '~/.venvs/syndicate/bin/python',
    [string] $LocalHome = '~/syndicate-prod',
    [string] $StateDir = 'C:\SyndicateProd\watchdog',
    [int] $TimeoutSeconds = 120,
    [string] $FleetTaskName = 'SyndicateLocalProduction',
    [switch] $TestToast
)

$ErrorActionPreference = 'Stop'
$RealertSeconds = 6 * 3600
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$logPath = Join-Path $StateDir 'watchdog.log'
$statePath = Join-Path $StateDir 'wsl_state.json'

function Write-Log([string] $line) {
    if ((Test-Path $logPath) -and ((Get-Item $logPath).Length -gt 5MB)) {
        Move-Item -Force $logPath "$logPath.1"
    }
    Add-Content -Path $logPath -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK'), $line) -Encoding utf8
}

function Show-Toast([string] $Title, [string] $Body) {
    try {
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
        if ($Body.Length -gt 400) { $Body = $Body.Substring(0, 397) + '...' }
        $t = [Security.SecurityElement]::Escape($Title)
        $b = [Security.SecurityElement]::Escape($Body)
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual></toast>")
        # The registered AppUserModelID of Windows PowerShell, so the toast is allowed without an installer.
        $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show(
            [Windows.UI.Notifications.ToastNotification]::new($xml))
        return $true
    } catch {
        Write-Log "TOAST_FAILED $($_.Exception.Message)"
        return $false
    }
}

if ($TestToast) {
    $shown = Show-Toast 'Syndicate fleet watchdog' 'Test notification: if you can read this, alerts will reach you.'
    Write-Log "TEST_TOAST shown=$shown"
    Write-Host "test toast shown=$shown"
    return
}

# ---- run the WSL-side check, bounded ---------------------------------------
$cmd = "$WslPython $WslRepo/scripts/local_watchdog.py --json --home $LocalHome"
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'wsl.exe'
$psi.Arguments = "-d $WslDistro -- bash -lc `"$cmd`""
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$stdout = ''
$reason = ''
try {
    $proc = [System.Diagnostics.Process]::Start($psi)
    $outTask = $proc.StandardOutput.ReadToEndAsync()
    if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
        try { $proc.Kill() } catch {}
        $reason = "no answer from WSL within $TimeoutSeconds s"
    } else {
        $stdout = $outTask.Result
    }
} catch {
    $reason = "could not start wsl.exe: $($_.Exception.Message)"
}

$result = $null
if (-not $reason) {
    $line = ($stdout -split "`n" | Where-Object { $_.Trim().StartsWith('{') } | Select-Object -Last 1)
    if ($line) {
        try { $result = $line | ConvertFrom-Json } catch { $reason = "unreadable watchdog output" }
    } else {
        $reason = "watchdog printed no result (WSL distro '$WslDistro' down, or the venv/repo missing)"
    }
}

# ---- Windows-side state: only for "WSL unreachable" -------------------------
$state = @{ unreachable_since = $null; last_alert = $null; reason = $null }
if (Test-Path $statePath) {
    try {
        $loaded = Get-Content $statePath -Raw | ConvertFrom-Json
        $state.unreachable_since = $loaded.unreachable_since
        $state.last_alert = $loaded.last_alert
        $state.reason = $loaded.reason
    } catch {}
}
$now = Get-Date

if ($reason) {
    $sendIt = $false
    if (-not $state.unreachable_since) {
        $state.unreachable_since = $now.ToString('o'); $sendIt = $true
    } elseif ((-not $state.last_alert) -or (($now - [datetime]$state.last_alert).TotalSeconds -ge $RealertSeconds)) {
        $sendIt = $true
    }
    $state.reason = $reason
    if ($sendIt) {
        $state.last_alert = $now.ToString('o')
        Show-Toast 'Syndicate fleet: UNREACHABLE' "$reason (since $($state.unreachable_since))" | Out-Null
    }
    Write-Log "UNREACHABLE alert=$sendIt $reason"
    $state | ConvertTo-Json | Set-Content -Path $statePath -Encoding utf8
    return
}

if ($state.unreachable_since) {
    Show-Toast 'Syndicate fleet: reachable again' "WSL answered again (was unreachable since $($state.unreachable_since): $($state.reason))" | Out-Null
    Write-Log "REACHABLE_AGAIN after $($state.unreachable_since)"
    @{ unreachable_since = $null; last_alert = $null; reason = $null } | ConvertTo-Json | Set-Content -Path $statePath -Encoding utf8
}

# AUTO-RECOVERY: the WSL-side decision (local_watchdog.recovery: supervisor down for two checks, capped 3/hour,
# paused by <home>/watchdog_no_autostart) says start the fleet. Starting it is a Windows action, so it lives here.
if ($result.recover) {
    try {
        Start-ScheduledTask -TaskName $FleetTaskName
        Write-Log "RECOVERY_START task=$FleetTaskName $($result.recovery.reason)"
    } catch {
        Write-Log "RECOVERY_START_FAILED task=$FleetTaskName $($_.Exception.Message)"
    }
}

if ($result.alert) {
    $shown = Show-Toast $result.title $result.message
    Write-Log "ALERT shown=$shown status=$($result.status) $($result.title) | $($result.message -replace "`n", ' | ')"
} else {
    Write-Log "OK status=$($result.status) findings=$(@($result.findings).Count)"
}
