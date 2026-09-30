<#
Register Syndicate local production to start at logon and restart if it dies.
Lane `local-production-host` [2026-09-30]. Runbook: docs/ai_context/local_production_runbook.md

  # Recommended: run inside WSL2 (gunicorn, redis, fcntl locks, /proc memory all work)
  powershell -ExecutionPolicy Bypass -File deploy\local\install_windows_task.ps1 -Mode Wsl -WslRepo ~/Syndicate

  # Fallback: native Windows (waitress web server; see the runbook's caveats)
  powershell -ExecutionPolicy Bypass -File deploy\local\install_windows_task.ps1 -Mode Native

  # Remove
  powershell -ExecutionPolicy Bypass -File deploy\local\install_windows_task.ps1 -Uninstall
#>
param(
    [ValidateSet('Wsl', 'Native')] [string] $Mode = 'Wsl',
    [string] $WslDistro = 'Ubuntu',
    [string] $WslRepo = '~/Syndicate',
    [string] $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string] $UpArgs = '',
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
    $command = "cd $WslRepo && exec python3 scripts/local_production.py up $UpArgs"
    $action = New-ScheduledTaskAction -Execute 'wsl.exe' -Argument "-d $WslDistro -- bash -lc `"$command`""
} else {
    $py = (Get-Command py -ErrorAction SilentlyContinue).Source
    if (-not $py) { $py = (Get-Command python -ErrorAction Stop).Source; $pyArgs = '' } else { $pyArgs = '-3 ' }
    $action = New-ScheduledTaskAction -Execute $py -Argument "${pyArgs}scripts\local_production.py up $UpArgs" -WorkingDirectory $RepoRoot
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
