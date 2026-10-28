<#
Register scripts/check_scheduled_task_registry.py to run every 2 hours. Lane `scheduled-task-registry-alert` [2026-10-28].

On 2026-10-28 the Claude desktop app lost every scheduled task, its missed-dispatch watchdog included, and
nothing alerted. This puts the check in Windows Task Scheduler, outside the registry it watches.

  powershell -ExecutionPolicy Bypass -File deploy\local\install_task_registry_check.ps1
  powershell -ExecutionPolicy Bypass -File deploy\local\install_task_registry_check.ps1 -Uninstall

The script is COPIED into -StateDir and the task runs that copy (a session worktree is deleted when its lane
closes and the primary tree lags origin/main). Re-run this installer to pick up a newer script.

Runs as YOU, only while you are logged on (the toast needs your desktop), starts a missed run as soon as the
machine wakes (the script itself refuses to judge a due time the machine slept through), never overlaps
itself, and runs on battery. pythonw.exe, so no console window flashes. Runs at :50 past every even hour, so
each of the watchdog's 09:15 / 13:15 / 17:15 / 21:15 runs is judged within ~5 min of its 90-min grace ending.
One line per run goes to <StateDir>\check.log.
#>
param(
    [string] $StateDir = 'C:\SyndicateProd\task_registry_check',
    [string] $Pythonw = '',
    [int] $EveryHours = 2,
    [string] $TaskName = 'SyndicateTaskRegistryCheck',
    [switch] $Uninstall
)

$ErrorActionPreference = 'Stop'

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "removed scheduled task $TaskName (log left in $StateDir)"
    return
}

if (-not $Pythonw) {
    $python = (& py -3 -c 'import sys; print(sys.executable)').Trim()
    $Pythonw = Join-Path (Split-Path $python -Parent) 'pythonw.exe'
}
if (-not (Test-Path $Pythonw)) { throw "pythonw.exe not found at $Pythonw (pass -Pythonw)" }

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$script = Join-Path $StateDir 'check_scheduled_task_registry.py'
Copy-Item -Force (Join-Path $PSScriptRoot '..\..\scripts\check_scheduled_task_registry.py') $script
$log = Join-Path $StateDir 'check.log'

# First run at the next HH:50 with HH even, so the 2 h cadence lands on 10:50, 14:50, 18:50 and 22:50.
$start = (Get-Date).Date.AddMinutes(50)
while ($start -le (Get-Date)) { $start = $start.AddHours($EveryHours) }

$action = New-ScheduledTaskAction -Execute $Pythonw -Argument "`"$script`" --log `"$log`"" -WorkingDirectory $StateDir
$trigger = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Hours $EveryHours)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description ('Alerts (Windows toast) when the Claude desktop app''s scheduled-task registry is lost or the dispatch ' +
                  'watchdog stops running (scripts/check_scheduled_task_registry.py). Lane scheduled-task-registry-alert.') `
    -Force | Out-Null
Write-Host "registered $TaskName every $EveryHours h from $($start.ToString('yyyy-MM-dd HH:mm')) -> $Pythonw $script"
Write-Host "log: $log"
