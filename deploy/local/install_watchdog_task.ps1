<#
Register the local production health watchdog to run every 5 minutes. Lane `local-prod-watchdog` [2026-10-02].
Runbook: docs/ai_context/local_production_runbook.md

  powershell -ExecutionPolicy Bypass -File deploy\local\install_watchdog_task.ps1 -WslDistro Ubuntu-24.04
  powershell -ExecutionPolicy Bypass -File deploy\local\install_watchdog_task.ps1 -Uninstall
  powershell -ExecutionPolicy Bypass -File deploy\local\install_watchdog_task.ps1 -NewNtfyTopic   # phone push

watchdog.ps1 is COPIED into -StateDir and the task runs that copy: a session worktree is
deleted when its lane closes, and the primary tree lags origin/main, so neither is a stable
path for a task that runs forever. Re-run this installer to pick up a newer watchdog.ps1.

The task runs as YOU, only while you are logged on (a notification needs your desktop),
starts a missed run as soon as the machine wakes, never overlaps itself, and runs on battery.
It is launched through `conhost.exe --headless` so no console window flashes every 5 minutes.

LOGGED-OFF ALERTS (lane watchdog-ntfy-alerts, 2026-10-14). A toast reaches nobody while you are logged off, and an
Interactive task does not even RUN then -- so neither alerts nor auto-recovery did. Two steps fix both:
  1. -NewNtfyTopic writes a long random topic to <StateDir>
tfy_topic.txt and prints it ONCE; subscribe to it in
     the ntfy phone app. watchdog.ps1 then pushes every alert there as well as toasting.
  2. In Task Scheduler, open SyndicateFleetWatchdog > General > "Run whether user is logged on or not" and enter
     your password (registering that from a script needs elevation and your password, so you do it by hand).
Re-running this installer later KEEPS a logged-off registration: it refreshes the script copy and leaves the task
alone, because re-registering would silently put it back to Interactive.
#>
param(
    [string] $WslDistro = 'Ubuntu-24.04',
    [string] $WslRepo = '~/Syndicate',
    [string] $WslPython = '~/.venvs/syndicate/bin/python',
    [string] $LocalHome = '~/syndicate-prod',
    [string] $StateDir = 'C:\SyndicateProd\watchdog',
    [int] $EveryMinutes = 5,
    [string] $TaskName = 'SyndicateFleetWatchdog',
    [switch] $Uninstall,
    [switch] $NewNtfyTopic
)

$ErrorActionPreference = 'Stop'

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "removed scheduled task $TaskName (state and log left in $StateDir)"
    return
}

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$script = Join-Path $StateDir 'watchdog.ps1'
Copy-Item -Force (Join-Path $PSScriptRoot 'watchdog.ps1') $script

if ($NewNtfyTopic) {
    $topicFile = Join-Path $StateDir 'ntfy_topic.txt'
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $topic = 'syndicate-fleet-' + (-join ($bytes | ForEach-Object { '{0:x2}' -f $_ }))
    Set-Content -Path $topicFile -Value $topic -Encoding ascii -NoNewline
    Write-Host "ntfy topic written to $topicFile -- subscribe to it in the ntfy app (server ntfy.sh):"
    Write-Host "  $topic"
    Write-Host "Anyone who knows this topic can read the alerts; do not paste it anywhere public."
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Principal.LogonType -ne 'Interactive') {
    Write-Host "kept $TaskName as registered (LogonType $($existing.Principal.LogonType), runs while logged off); script refreshed -> $script"
    return
}

$psArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -WslDistro $WslDistro -WslRepo $WslRepo " +
          "-WslPython $WslPython -LocalHome $LocalHome -StateDir `"$StateDir`""
$action = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument "--headless powershell.exe $psArgs"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description 'Syndicate local production health watchdog (scripts/local_watchdog.py via WSL); alerts as Windows notifications.' `
    -Force | Out-Null
Write-Host "registered $TaskName every $EveryMinutes min -> $script"
Write-Host "log: $(Join-Path $StateDir 'watchdog.log')"
