<#
Register SyndicateLanForward: keeps http://<lan-ip>:10000 forwarded to the WSL web across reboots,
sleep/resume, Wi-Fi reconnects and DHCP address changes. Lane `lan-forward-guard` [2026-10-12].
Runbook: docs/ai_context/local_production_runbook.md section 5.

Run ONCE from an ADMIN PowerShell (it registers a SYSTEM task and runs the guard once):
  powershell -ExecutionPolicy Bypass -File deploy\local\install_lan_forward_task.ps1
  powershell -ExecutionPolicy Bypass -File deploy\local\install_lan_forward_task.ps1 -Uninstall

WHY: the web binds 127.0.0.1 inside WSL, so LAN clients reach it through a Windows portproxy rule
(<lan-ip>:10000 -> 127.0.0.1:10000) served by the IP Helper service. iphlpsvc binds the rule's
listener only when it starts; if the LAN address is not up yet (boot, resume) the bind fails silently
and is never retried. Measured 2026-10-09: rule + firewall rule present, iphlpsvc Running, no listener.

lan_forward_guard.ps1 is COPIED into -StateDir and the task runs that copy, for the same reason as
install_watchdog_task.ps1: a session worktree is deleted when its lane closes and the primary tree lags
origin/main, so neither is a stable path for a task that runs forever. Re-run to pick up a newer guard.

Triggers: at startup (+30 s), on every network connect (NetworkProfile event 10000), every 5 minutes.
SYSTEM because restarting iphlpsvc and editing portproxy need it. -Force on that restart also stops
Tailscale (an iphlpsvc dependent); the guard restarts any dependent that was running.

Firewall: the guard does not create the inbound rule. One allowing TCP 10000 on the Private profile
("Syndicate local web (LAN)") existed on 2026-10-09; on a new host create it once:
  New-NetFirewallRule -DisplayName 'Syndicate local web (LAN)' -Direction Inbound -Protocol TCP -LocalPort 10000 -Profile Private -Action Allow
#>
param(
    [string] $StateDir = 'C:\SyndicateProd\lan-forward',
    [int] $Port = 10000,
    [string] $TaskName = 'SyndicateLanForward',
    [int] $EveryMinutes = 5,
    [switch] $Uninstall
)

$ErrorActionPreference = 'Stop'

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Run this from an ADMIN PowerShell (right-click > Run as administrator).' }

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "removed scheduled task $TaskName (portproxy rule, state and log left in $StateDir)"
    return
}

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$guard = Join-Path $StateDir 'lan_forward_guard.ps1'
Copy-Item -Force (Join-Path $PSScriptRoot 'lan_forward_guard.ps1') $guard
$log = Join-Path $StateDir 'lan_forward.log'

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$guard`" -Port $Port -LogPath `"$log`""

$atBoot = New-ScheduledTaskTrigger -AtStartup
$atBoot.Delay = 'PT30S'
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes)
$evClass = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler
$onConnect = New-CimInstance -CimClass $evClass -ClientOnly
$onConnect.Enabled = $true
$onConnect.Subscription = '<QueryList><Query Id="0" Path="Microsoft-Windows-NetworkProfile/Operational">' +
    '<Select Path="Microsoft-Windows-NetworkProfile/Operational">*[System[(EventID=10000)]]</Select></Query></QueryList>'

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($atBoot, $onConnect, $every) `
    -Settings $settings -Principal $principal -Force `
    -Description "Syndicate: keep <lan-ip>:$Port portproxy to the WSL web bound (re-points on DHCP change, restarts iphlpsvc if the listener is missing)." |
    Out-Null
Write-Host "registered $TaskName (startup, network connect, every $EveryMinutes min) -> $guard"

Write-Host 'running the guard once now...'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $guard -Port $Port -LogPath $log
Write-Host "guard exit code: $LASTEXITCODE"
Get-NetTCPConnection -LocalPort $Port -State Listen | Format-Table LocalAddress, LocalPort
Get-Content (Join-Path $StateDir 'last_run.txt') -ErrorAction SilentlyContinue
Get-Content $log -Tail 5 -ErrorAction SilentlyContinue
