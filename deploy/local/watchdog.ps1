<#
Windows side of the local production health watchdog. Lane `local-prod-watchdog` [2026-10-02].
Runs `scripts/local_watchdog.py --json` inside WSL and turns its `alert` into a Windows
notification. Also alerts when WSL does not answer at all -- the one failure the
WSL-side check cannot report about itself.

Normally run every 5 minutes by the task `install_watchdog_task.ps1` registers.

  powershell -NoProfile -ExecutionPolicy Bypass -File watchdog.ps1              # one check
  powershell -NoProfile -ExecutionPolicy Bypass -File watchdog.ps1 -TestToast   # prove notifications show

Windows-side state and a one-line-per-run log live in -StateDir (default C:\SyndicateProd\watchdog).

WSL UNREACHABLE BY EMAIL `[2026-10-20, lane watchdog-unreachable-email]`. A toast reaches nobody away from the
desk, and while WSL is down the WSL-side mailer (scripts/alert_mailer.py) cannot run, so this script sends the
email itself, through the same Gmail account: once WSL has been unreachable for -EmailAfterMinutes (default 10;
48 episodes 10-02..10-19 all recovered alone, longest 25.7 min, 11 lasted >= 10 min), again every 6 h while it
stays down, and once when it answers again. A failed send is retried on the next run.
The SMTP settings live in <StateDir>\smtp_alerts.json, the password DPAPI-encrypted under YOUR Windows account
(only that login on this machine can decrypt it) and the file ACL'd to you. Written once by:

  powershell -NoProfile -ExecutionPolicy Bypass -File watchdog.ps1 -SetupEmail                  # copy from WSL alerts.env
  powershell -NoProfile -ExecutionPolicy Bypass -File watchdog.ps1 -SetupEmail -PromptPassword  # type them instead
  powershell -NoProfile -ExecutionPolicy Bypass -File watchdog.ps1 -TestEmail                   # send one test email
  ... -WslDistro DRILL-bogus -EmailAfterMinutes 0 -Drill   # synthetic unreachable: emails at once, subject [Syndicate DRILL]

DEAD-MAN'S SWITCH. Nothing on this machine can report the machine itself asleep, off or offline. Every run ends
with one GET to the healthchecks.io ping URL in <StateDir>\heartbeat_url.txt (none -> no ping); healthchecks.io
emails when the pings stop. A run that throws before the end skips the ping, so a broken watchdog alerts too.

  powershell -NoProfile -ExecutionPolicy Bypass -File watchdog.ps1 -SetupHeartbeat https://hc-ping.com/<uuid>

ONE WRITER, NEWEST OBSERVATION WINS `[2026-10-20, lane watchdog-stale-writer]`. The task's PT4M limit kills conhost.exe
but NOT this powershell.exe, so a slow run lives on and used to write wsl_state.json LATE, over a newer run's state
(10-20: last_email wiped twice -- in a real outage that is a duplicate UNREACHABLE email or a lost 'reachable again').
Now: (1) the read-modify-write of wsl_state.json holds wsl_state.lock (an exclusive file handle, released by the OS
even when the process is killed), (2) the state carries `observed_at`, when the WSL check that wrote it finished, and
a run whose own check finished EARLIER skips the state block (log `STATE_STALE`) instead of overwriting it, and (3)
the run works to -DeadlineSeconds (default 200 s of the 240 s limit, counted from the process start): the WSL check gets what is left after a reserve
for the lock, SMTP and the heartbeat, and stdout is read line by line, so a wsl.exe that exits with its pipe still
held open no longer blocks the run. Every log line carries `run=<pid>`, so two runs' lines can be told apart.
#>
param(
    [string] $WslDistro = 'Ubuntu-24.04',
    [string] $WslRepo = '~/Syndicate',
    [string] $WslPython = '~/.venvs/syndicate/bin/python',
    [string] $LocalHome = '~/syndicate-prod',
    [string] $StateDir = 'C:\SyndicateProd\watchdog',
    [int] $TimeoutSeconds = 120,
    [string] $FleetTaskName = 'SyndicateLocalProduction',
    [int] $EmailAfterMinutes = 10,
    [int] $DeadlineSeconds = 200,
    [switch] $TestToast,
    [switch] $SetupEmail,
    [switch] $PromptPassword,
    [switch] $TestEmail,
    [switch] $Drill,
    [string] $SetupHeartbeat = ''
)

$ErrorActionPreference = 'Stop'
# The deadline counts from the PROCESS start: on 10-20 a task run took 65 s to get from launch to wsl.exe.
$scriptStarted = Get-Date
$runStarted = try { (Get-Process -Id $PID).StartTime } catch { $scriptStarted }
$RealertSeconds = 6 * 3600
# Kept free after the WSL check: lock wait + SMTP (20 s timeout; one send took 34 s on 10-20) + heartbeat (10 s).
$ReserveSeconds = 70
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$logPath = Join-Path $StateDir 'watchdog.log'
$statePath = Join-Path $StateDir 'wsl_state.json'
$stateLockPath = Join-Path $StateDir 'wsl_state.lock'
$emailConfigPath = Join-Path $StateDir 'smtp_alerts.json'
$heartbeatPath = Join-Path $StateDir 'heartbeat_url.txt'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

function Write-Log([string] $line) {
    if ((Test-Path $logPath) -and ((Get-Item $logPath).Length -gt 5MB)) {
        Move-Item -Force $logPath "$logPath.1"
    }
    Add-Content -Path $logPath -Value ("{0} run={1} {2}" -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK'), $PID, $line) -Encoding utf8
}

function Get-Elapsed { return [int][math]::Round(((Get-Date) - $runStarted).TotalSeconds) }
function Get-SecondsLeft { return $DeadlineSeconds - (Get-Elapsed) }
function Get-StartupSeconds { return [int][math]::Round(($scriptStarted - $runStarted).TotalSeconds) }

# An exclusive handle on wsl_state.lock; $null if another run still holds it after $WaitSeconds.
function Enter-StateLock([int] $WaitSeconds) {
    $until = (Get-Date).AddSeconds([math]::Max(0, $WaitSeconds))
    while ($true) {
        try {
            return [IO.File]::Open($stateLockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        } catch [System.IO.IOException] {
            if ((Get-Date) -ge $until) { return $null }
            Start-Sleep -Milliseconds 250
        }
    }
}

# tmp + rename, so a reader never sees half a file (an unreadable state used to read as "no episode").
function Save-State($State) {
    $State.observed_at = $observedAt.ToString('o')
    $State.run_pid = $PID
    $tmp = "$statePath.tmp"
    $State | ConvertTo-Json | Set-Content -Path $tmp -Encoding utf8
    Move-Item -Force $tmp $statePath
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

function Set-OwnerOnlyAcl([string] $Path) {
    $me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $Path /inheritance:r /grant:r "${me}:F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls failed on $Path (exit $LASTEXITCODE)" }
}

function Format-Central([datetime] $When) {
    $ct = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId($When, 'Central Standard Time')
    return $ct.ToString('yyyy-MM-dd h:mm tt') + ' CT'
}

# The password is never printed, logged, or held as plain text longer than the copy from alerts.env needs.
function Send-Email([string] $Subject, [string] $Body) {
    if (-not (Test-Path $emailConfigPath)) {
        Write-Log "EMAIL_OFF no $emailConfigPath (run -SetupEmail)"
        return $false
    }
    $client = $null; $message = $null
    try {
        $cfg = Get-Content $emailConfigPath -Raw | ConvertFrom-Json
        $secret = ConvertTo-SecureString $cfg.password_dpapi
        $client = New-Object System.Net.Mail.SmtpClient($cfg.host, [int]$cfg.port)
        $client.EnableSsl = $true
        $client.Timeout = 20000
        $client.Credentials = New-Object System.Net.NetworkCredential($cfg.user, $secret)
        $tag = if ($Drill) { '[Syndicate DRILL]' } else { '[Syndicate]' }
        $message = New-Object System.Net.Mail.MailMessage($cfg.user, $cfg.to, "$tag $Subject", $Body)
        $client.Send($message)
        Write-Log "EMAIL_SENT subject='$Subject'"
        return $true
    } catch {
        $err = "$($_.Exception.GetType().Name): $($_.Exception.Message)"
        if ($_.Exception.InnerException) { $err += " / $($_.Exception.InnerException.Message)" }
        if ($err.Length -gt 200) { $err = $err.Substring(0, 200) }
        Write-Log "EMAIL_FAILED subject='$Subject' $err"
        return $false
    } finally {
        if ($message) { $message.Dispose() }
        if ($client) { $client.Dispose() }
    }
}

function Send-Heartbeat {
    if (-not (Test-Path $heartbeatPath)) { return }
    $url = (Get-Content $heartbeatPath -Raw).Trim()
    if (-not $url) { return }
    try {
        Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10 -Method Get | Out-Null
    } catch {
        # The URL's path is the check's secret: log the host only.
        Write-Log "HEARTBEAT_FAILED host=$(([uri]$url).Host) $($_.Exception.Message)"
    }
}

if ($TestToast) {
    $shown = Show-Toast 'Syndicate fleet watchdog' 'Test notification: if you can read this, alerts will reach you.'
    Write-Log "TEST_TOAST shown=$shown"
    Write-Host "test toast shown=$shown"
    return
}

if ($SetupEmail) {
    if ($PromptPassword) {
        $user = (Read-Host 'Gmail address').Trim()
        $typed = Read-Host 'Gmail app password' -AsSecureString
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($typed))
        $values = @{ SYNDICATE_ALERT_SMTP_USER = $user; SYNDICATE_ALERT_SMTP_PASSWORD = $plain }
    } else {
        # Same parsing as local_production.parse_env_file: KEY=VALUE, '#' comments, optional 'export ', surrounding quotes.
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = 'wsl.exe'
        $psi.Arguments = "-d $WslDistro -- bash -lc `"cat $LocalHome/alerts.env`""
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.StandardOutputEncoding = [Text.Encoding]::UTF8
        $proc = [System.Diagnostics.Process]::Start($psi)
        $text = $proc.StandardOutput.ReadToEnd()
        $proc.WaitForExit()
        if ($proc.ExitCode -ne 0) { throw "could not read $LocalHome/alerts.env in WSL '$WslDistro' (exit $($proc.ExitCode))" }
        $values = @{}
        foreach ($raw in ($text -split "`n")) {
            $line = $raw.Trim()
            if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) { continue }
            if ($line.StartsWith('export ')) { $line = $line.Substring(7) }
            $key, $value = $line.Split('=', 2)
            $key = $key.Trim(); $value = $value.Trim()
            if ($value.Length -ge 2 -and $value[0] -eq $value[-1] -and (@('"', "'") -contains [string]$value[0])) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            $values[$key] = $value
        }
    }
    $user = [string]$values['SYNDICATE_ALERT_SMTP_USER']
    $plain = ([string]$values['SYNDICATE_ALERT_SMTP_PASSWORD']) -replace ' ', ''
    if (-not $user -or -not $plain) { throw 'no SYNDICATE_ALERT_SMTP_USER / SYNDICATE_ALERT_SMTP_PASSWORD found; nothing saved' }
    $to = if ($values['SYNDICATE_ALERT_EMAIL_TO']) { [string]$values['SYNDICATE_ALERT_EMAIL_TO'] } else { $user }
    $smtpHost = if ($values['SYNDICATE_ALERT_SMTP_HOST']) { [string]$values['SYNDICATE_ALERT_SMTP_HOST'] } else { 'smtp.gmail.com' }
    $port = if ($values['SYNDICATE_ALERT_SMTP_PORT']) { [int]$values['SYNDICATE_ALERT_SMTP_PORT'] } else { 587 }
    $encrypted = ConvertTo-SecureString $plain -AsPlainText -Force | ConvertFrom-SecureString
    $plain = $null; $values = $null
    $tmp = "$emailConfigPath.tmp"
    if (-not (Test-Path $tmp)) { New-Item -ItemType File -Path $tmp | Out-Null }
    Set-OwnerOnlyAcl $tmp
    @{ user = $user; to = $to; host = $smtpHost; port = $port; password_dpapi = $encrypted } |
        ConvertTo-Json | Set-Content -Path $tmp -Encoding utf8
    Move-Item -Force $tmp $emailConfigPath
    Set-OwnerOnlyAcl $emailConfigPath
    Write-Log "EMAIL_SETUP from=$user to=$to host=${smtpHost}:$port"
    Write-Host "saved $emailConfigPath (from=$user to=$to host=${smtpHost}:$port password_set=True, DPAPI, owner-only ACL)"
    return
}

if ($TestEmail) {
    $sent = Send-Email 'test email from the Windows fleet watchdog' ("If you can read this, the Windows-side watchdog on " +
        "$env:COMPUTERNAME can email you when WSL is unreachable.`nSent $(Format-Central (Get-Date)).")
    Write-Host "test email sent=$sent (details in $logPath)"
    return
}

if ($SetupHeartbeat) {
    if (-not $SetupHeartbeat.StartsWith('https://')) { throw 'the heartbeat URL must be https://' }
    Set-Content -Path $heartbeatPath -Value $SetupHeartbeat.Trim() -Encoding ascii
    Set-OwnerOnlyAcl $heartbeatPath
    Send-Heartbeat
    Write-Log "HEARTBEAT_SETUP host=$(([uri]$SetupHeartbeat).Host)"
    Write-Host "saved $heartbeatPath and sent one ping (a failure would be logged as HEARTBEAT_FAILED in $logPath)"
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
$pipeNote = ''
# The check gets what the deadline leaves after the reserve (normally the full -TimeoutSeconds), never under 30 s:
# it takes ~4 s when healthy, and a too-short budget would read as a false UNREACHABLE.
$checkSeconds = [math]::Max(30, [math]::Min($TimeoutSeconds, (Get-SecondsLeft) - $ReserveSeconds))
try {
    $proc = [System.Diagnostics.Process]::Start($psi)
    $null = $proc.StandardError.ReadToEndAsync()   # drained, so a chatty stderr cannot fill its pipe and stall the child
    # Line by line, never ReadToEnd: ReadToEnd waits for EOF, which a process still holding the pipe after wsl.exe
    # exits can postpone indefinitely -- with no timeout on it at all.
    $checkUntil = (Get-Date).AddSeconds($checkSeconds)
    $lines = New-Object System.Collections.Generic.List[string]
    $pending = $null; $eof = $false; $exitedAt = $null
    while ($true) {
        if (-not $pending) { $pending = $proc.StandardOutput.ReadLineAsync() }
        if ($pending.Wait(250)) {
            $text = $pending.Result; $pending = $null
            if ($null -eq $text) { $eof = $true; break }
            $lines.Add($text)
            continue
        }
        if ((Get-Date) -ge $checkUntil) { break }
        if ($proc.HasExited) {
            if (-not $exitedAt) { $exitedAt = Get-Date }
            elseif (((Get-Date) - $exitedAt).TotalSeconds -ge 5) { break }
        }
    }
    $stdout = $lines -join "`n"
    if (-not $eof -and -not $proc.HasExited) {
        try { $proc.Kill() } catch {}
        $reason = "no answer from WSL within $checkSeconds s"
    } elseif (-not $eof) {
        $pipeNote = ' stdout_open_after_exit=1'
    }
} catch {
    $reason = "could not start wsl.exe: $($_.Exception.Message)"
}
$observedAt = [DateTimeOffset]::Now

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
# One run at a time, and never an older observation over a newer one (see the header): the whole read-modify-write,
# including the email it may send, holds wsl_state.lock.
$stateLock = Enter-StateLock ((Get-SecondsLeft) - 45)
try {
    $state = @{ unreachable_since = $null; last_alert = $null; reason = $null; last_email = $null }
    $diskObservedAt = $null; $diskPid = $null
    if (Test-Path $statePath) {
        try {
            $loaded = Get-Content $statePath -Raw | ConvertFrom-Json
            $state.unreachable_since = $loaded.unreachable_since
            $state.last_alert = $loaded.last_alert
            $state.reason = $loaded.reason
            $state.last_email = $loaded.last_email
            if ($loaded.observed_at) { $diskObservedAt = [DateTimeOffset]$loaded.observed_at; $diskPid = $loaded.run_pid }
        } catch {}
    }
    $skip = ''
    if (-not $stateLock) {
        $skip = "STATE_BUSY wsl_state.lock still held after the wait"
    } elseif ($diskObservedAt -and $diskObservedAt -gt $observedAt) {
        $skip = "STATE_STALE observed_at=$($observedAt.ToString('o')) but the state holds a newer check " +
            "(observed_at=$($diskObservedAt.ToString('o')) run=$diskPid)"
    }
    $now = Get-Date

    if ($reason -and $skip) {
        Write-Log "$skip -- left it as is; this run saw: $reason"
    } elseif ($reason) {
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
        # EMAIL: after -EmailAfterMinutes of being down (short blips stay toast-only), then every 6 h. Not stamped
        # until a send succeeds, so a failed send is retried on the next run.
        $since = [datetime]$state.unreachable_since
        $downMinutes = [int][math]::Floor(($now - $since).TotalMinutes)
        $emailDue = ($downMinutes -ge $EmailAfterMinutes) -and
            ((-not $state.last_email) -or (($now - [datetime]$state.last_email).TotalSeconds -ge $RealertSeconds))
        if ($emailDue) {
            $body = @(
                "The Windows watchdog on $env:COMPUTERNAME has had no answer from WSL (distro '$WslDistro') for $downMinutes min.",
                "",
                "Reason: $reason",
                "Unreachable since: $(Format-Central $since)",
                "",
                "While WSL is down the whole local fleet is down: odds refresh, live Kalshi/Polymarket execution, and the",
                "WSL-side execution alerts (which cannot email while WSL is down). The watchdog's auto-recovery cannot",
                "help either, because it needs WSL to answer.",
                "",
                "You will get a 'reachable again' email when WSL answers. This repeats every 6 h while it stays down.",
                "Runbook: docs/ai_context/local_production_runbook.md, section 'Health watchdog'."
            ) -join "`n"
            if (Send-Email "fleet UNREACHABLE: WSL has not answered for $downMinutes min" $body) {
                $state.last_email = $now.ToString('o')
            }
        }
        Write-Log "UNREACHABLE alert=$sendIt email_due=$emailDue down_min=$downMinutes took_s=$(Get-Elapsed) startup_s=$(Get-StartupSeconds) $reason"
        Save-State $state
    } elseif ($skip) {
        Write-Log "$skip -- left it as is; this run saw WSL answer$pipeNote"
    } elseif ($state.unreachable_since) {
        Show-Toast 'Syndicate fleet: reachable again' "WSL answered again (was unreachable since $($state.unreachable_since): $($state.reason))" | Out-Null
        Write-Log "REACHABLE_AGAIN after $($state.unreachable_since)"
        if ($state.last_email) {
            # Only an episode that emailed gets a closing email; a toast-only blip stays toast-only.
            $since = [datetime]$state.unreachable_since
            $downMinutes = [int][math]::Floor(($now - $since).TotalMinutes)
            Send-Email "fleet reachable again after $downMinutes min" (
                "WSL on $env:COMPUTERNAME answered again at $(Format-Central $now).`n" +
                "It was unreachable from $(Format-Central $since) ($downMinutes min): $($state.reason)`n`n" +
                "The WSL-side watchdog resumes its checks (and execution alerts) from this run on.") | Out-Null
        }
        Save-State @{ unreachable_since = $null; last_alert = $null; reason = $null; last_email = $null }
    } else {
        Save-State $state   # nothing changed, but observed_at is stamped: an older run can no longer write over it
    }
} finally {
    if ($stateLock) { $stateLock.Dispose() }
}
if ($reason) {
    Send-Heartbeat
    return
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
    Write-Log "ALERT shown=$shown status=$($result.status) took_s=$(Get-Elapsed) startup_s=$(Get-StartupSeconds)$pipeNote $($result.title) | $($result.message -replace "`n", ' | ')"
} else {
    Write-Log "OK status=$($result.status) findings=$(@($result.findings).Count) took_s=$(Get-Elapsed) startup_s=$(Get-StartupSeconds)$pipeNote"
}

Send-Heartbeat
