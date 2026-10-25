<#
Register the free news collector (injuries, referee crews, NHL scratches) to run every 5 minutes.
Lane `news-collectors-backfill` [2026-10-13]. Script: scripts/collect_news_snapshots.py (no keys, no OddsAPI, no spend).
5, not 10 (user 2026-10-25, lane news-availability-gate): an NHL scratch could sit up to 10 min before the board saw it.

  powershell -ExecutionPolicy Bypass -File deploy\local\install_news_collector_task.ps1
  powershell -ExecutionPolicy Bypass -File deploy\local\install_news_collector_task.ps1 -Uninstall

The task runs the FLEET checkout's copy of the script (`-WslRepo`, default ~/Syndicate), so a session worktree being
deleted cannot break it; a fleet fast-forward picks up a newer collector with no re-install. Output is append-only under
`<LocalHome>/data/news/`, one log line per run in `<LocalHome>/logs/news_collector.log`.

Same task shape as SyndicateFleetWatchdog: runs as YOU while logged on, starts a missed run on wake, never overlaps
itself, runs on battery, launched through `conhost.exe --headless` so no window flashes. `nice -n 19` inside WSL: the
fleet shares this machine.
#>
param(
    [string] $WslDistro = 'Ubuntu-24.04',
    [string] $WslRepo = '~/Syndicate',
    [string] $WslPython = '~/.venvs/syndicate/bin/python',
    [string] $LocalHome = '~/syndicate-prod',
    [int] $EveryMinutes = 5,
    [string] $TaskName = 'SyndicateNewsCollector',
    [switch] $Uninstall
)

$ErrorActionPreference = 'Stop'

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "removed scheduled task $TaskName (data left in $LocalHome/data/news)"
    return
}

$inner = "nice -n 19 $WslPython $WslRepo/scripts/collect_news_snapshots.py --data-root $LocalHome/data " +
         ">> $LocalHome/logs/news_collector.log 2>&1"
$wslArgs = "-d $WslDistro -- bash -lc `"$inner`""
$action = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument "--headless wsl.exe $wslArgs"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description 'Syndicate free news collector: ESPN injuries (NBA/NHL/NFL/WNBA), NBA referee crews, NHL officials + scratches. No OddsAPI.' `
    -Force | Out-Null
Write-Host "registered $TaskName every $EveryMinutes min -> $WslRepo/scripts/collect_news_snapshots.py"
Write-Host "data: $LocalHome/data/news   log: $LocalHome/logs/news_collector.log"
