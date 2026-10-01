<#
Register Syndicate local production to start at logon and restart if it dies.
Lane `local-production-host` [2026-09-30]. Runbook: docs/ai_context/local_production_runbook.md

  # Recommended: run inside WSL2 (gunicorn, redis, fcntl locks, /proc memory all work)
  powershell -ExecutionPolicy Bypass -File deploy\local\install_windows_task.ps1 -Mode Wsl -WslDistro Ubuntu-24.04 `
      -WslRepo ~/Syndicate -LocalHome ~/syndicate-prod
  (-WslPython defaults to the runbook's venv, ~/.venvs/syndicate/bin/python.)

  # Fallback: native Windows (waitress web server; see the runbook's caveats)
  powershell -ExecutionPolicy Bypass -File deploy\local\install_windows_task.ps1 -Mode Native `
      -LocalHome C:\SyndicateProd\home -GlobalArgs '--state file' `
      -Python C:\Users\<you>\AppData\Local\Programs\Python\Python311-x64\python.exe

  Native needs all three on a real machine (first native-Windows setup, 2026-09-30):
  -LocalHome   without it `up` resolves %LOCALAPPDATA%\SyndicateProd and boots a
               NEW, EMPTY fleet beside the one you seeded.
  -GlobalArgs  --state/--port/--home are GLOBAL flags and must precede `up`;
               -UpArgs goes after it.
  -Python      `py -3` picks whichever 3.x the launcher prefers; that machine had
               both Python311-x64 and Python311-arm64.
  The supervisor's own stdout goes to <LocalHome>\logs\supervisor.log.

  # Remove
  powershell -ExecutionPolicy Bypass -File deploy\local\install_windows_task.ps1 -Uninstall
#>
param(
    [ValidateSet('Wsl', 'Native')] [string] $Mode = 'Wsl',
    [string] $WslDistro = 'Ubuntu',
    [string] $WslRepo = '~/Syndicate',
    [string] $WslPython = '~/.venvs/syndicate/bin/python',
    [string] $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string] $UpArgs = '',
    [string] $GlobalArgs = '',
    [string] $LocalHome = '',
    [string] $Python = '',
    [string] $TaskName = 'SyndicateLocalProduction',
    [switch] $Uninstall
)

$ErrorActionPreference = 'Stop'

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "removed scheduled task $TaskName"
    return
}

if ($Mode -eq 'Wsl') {
    # `exec` so the supervisor is the process WSL keeps alive; `bash -lc` so the
    # user's profile (PATH, venv activation) applies.
    # -WslPython: Ubuntu 24.04's `python3` is 3.12 with none of the requirements
    # installed (PEP 668); the runbook's venv is the interpreter that has them.
    # -GlobalArgs (--state/--port/--home) must precede `up`. -LocalHome is a
    # LINUX path here; the supervisor's stdout goes to <home>/logs/supervisor.log.
    $homeArg = ''
    $redirect = ''
    if ($LocalHome) {
        $homeArg = "--home $LocalHome "
        $redirect = " >> $LocalHome/logs/supervisor.log 2>&1"
    }
    $mkLogs = if ($LocalHome) { "mkdir -p $LocalHome/logs && " } else { '' }
    $command = "${mkLogs}cd $WslRepo && exec $WslPython scripts/local_production.py $homeArg$GlobalArgs up $UpArgs$redirect"
    $action = New-ScheduledTaskAction -Execute 'wsl.exe' -Argument "-d $WslDistro -- bash -lc `"$command`""
} else {
    if ($Python) {
        if (-not (Test-Path $Python)) { throw "-Python not found: $Python" }
        $py = $Python; $pyArgs = ''
    } else {
        $py = (Get-Command py -ErrorAction SilentlyContinue).Source
        if (-not $py) { $py = (Get-Command python -ErrorAction Stop).Source; $pyArgs = '' } else { $pyArgs = '-3 ' }
    }
    $homeArg = ''
    if ($LocalHome) { $homeArg = "--home `"$LocalHome`" " }
    $inner = "`"$py`" ${pyArgs}scripts\local_production.py $homeArg$GlobalArgs up $UpArgs"
    if ($LocalHome) {
        New-Item -ItemType Directory -Force (Join-Path $LocalHome 'logs') | Out-Null
        # cmd /c so the supervisor's own stdout lands somewhere; a task has no console.
        $log = Join-Path $LocalHome 'logs\supervisor.log'
        $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$inner >> `"$log`" 2>&1`"" -WorkingDirectory $RepoRoot
    } else {
        $action = New-ScheduledTaskAction -Execute $py -Argument "${pyArgs}scripts\local_production.py $GlobalArgs up $UpArgs" -WorkingDirectory $RepoRoot
    }
}

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# Restart on failure (every minute, many times); never stop it for running long;
# run on battery; do not start a second copy.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Syndicate production (web + refresh-worker + live-odds-worker) -- scripts/local_production.py' -Force | Out-Null

Write-Host "registered scheduled task '$TaskName' ($Mode). Start now with:  Start-ScheduledTask -TaskName $TaskName"
Write-Host ''
Write-Host 'Keep the machine awake or the workers stall (Modern Standby suspends them):'
Write-Host '  powercfg /change standby-timeout-ac 0'
Write-Host '  powercfg /change hibernate-timeout-ac 0'
