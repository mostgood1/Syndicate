<#
Keep the Syndicate web reachable from the LAN: <lan-ip>:<Port> -> 127.0.0.1:<Port> (WSL localhost forwarding).

The web binds 127.0.0.1 inside WSL, so the LAN path is a Windows portproxy rule served by the IP Helper
service (iphlpsvc). iphlpsvc binds a rule's listener only at its own start; if the listen address is not
on an interface yet (boot before Wi-Fi/DHCP, resume from sleep) the bind fails silently and is never
retried. Measured 2026-10-09: rule 10.0.0.199:10000 present, firewall rule present, iphlpsvc Running,
and NO listener on 10.0.0.199:10000 -- every LAN connection refused.

Each run: wait for the LAN address, re-point the rule if DHCP moved it, and restart iphlpsvc if the
listener is missing. Idempotent; a healthy run changes nothing. Runs as SYSTEM (scheduled task
SyndicateLanForward). Install with deploy\local\install_lan_forward_task.ps1, which COPIES this file into
-StateDir and registers the copy. Lane `lan-forward-guard` [2026-10-12]; runbook section 5.

Every run overwrites <StateDir>\last_run.txt ("<time> ok|repaired|FAILED|no-lan-address <ip/port> listeners=...");
lan_forward.log records repairs only. A stale last_run.txt means the TASK is not firing, not that the forward is fine.
#>
param(
    [int] $Port = 10000,
    [string] $ConnectAddress = '127.0.0.1',
    [string] $InterfaceAlias = '',      # empty = the interface holding the default route (Tailscale/vEthernet skipped)
    [int] $WaitSeconds = 180,
    [string] $LogPath = 'C:\SyndicateProd\lan-forward\lan_forward.log'
)

$ErrorActionPreference = 'Stop'

function Write-Log([string] $msg) {
    try {
        if ((Test-Path $LogPath) -and (Get-Item $LogPath).Length -gt 1MB) {
            Move-Item -Force $LogPath "$LogPath.1"
        }
        Add-Content -Path $LogPath -Value ("{0} {1}" -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $msg)
    } catch { }
}

function Write-Heartbeat([string] $state) {
    # Overwritten each run (no growth): proves the task is firing, which the repair-only log cannot.
    try {
        $listeners = (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object LocalAddress) -join ','
        Set-Content -Path (Join-Path (Split-Path $LogPath) 'last_run.txt') -Encoding ascii -Value (
            "{0} {1} listeners={2}" -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $state, $listeners)
    } catch { }
}

function Get-LanAddress {
    $routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
        Sort-Object { $_.RouteMetric + $_.InterfaceMetric }
    foreach ($r in $routes) {
        $alias = (Get-NetIPInterface -InterfaceIndex $r.InterfaceIndex -AddressFamily IPv4).InterfaceAlias
        if ($InterfaceAlias -and $alias -ne $InterfaceAlias) { continue }
        if (-not $InterfaceAlias -and $alias -match 'Tailscale|vEthernet|Loopback') { continue }
        $ip = Get-NetIPAddress -InterfaceIndex $r.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notlike '169.254.*' } |
            Select-Object -First 1
        if ($ip) { return $ip.IPAddress }
    }
    return $null
}

function Test-Listener([string] $ip) {
    [bool](Get-NetTCPConnection -LocalAddress $ip -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

# 1. Wait for the LAN address (boot / resume / reconnect).
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$ip = Get-LanAddress
while (-not $ip -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    $ip = Get-LanAddress
}
if (-not $ip) {
    Write-Log "no LAN IPv4 within ${WaitSeconds}s; nothing to do (network-connect trigger will re-run)"
    Write-Heartbeat "no-lan-address"
    exit 0
}

# 2. The rule must listen on the CURRENT address. Registry is the portproxy store: name 'listen/port', data 'connect/port'.
$regPath = 'HKLM:\SYSTEM\CurrentControlSet\Services\PortProxy\v4tov4\tcp'
$rules = @{}
if (Test-Path $regPath) {
    $props = Get-ItemProperty $regPath
    foreach ($p in $props.PSObject.Properties) {
        if ($p.Name -like '*/*' -and $p.Name -notlike 'PS*') { $rules[$p.Name] = [string] $p.Value }
    }
}
$want = "$ip/$Port"
$changed = $false
if (-not $rules.ContainsKey($want)) {
    foreach ($name in @($rules.Keys)) {
        $listenAddr, $listenPort = $name -split '/'
        if ($listenPort -eq "$Port" -and $listenAddr -notin @('127.0.0.1', '0.0.0.0', '*')) {
            & netsh interface portproxy delete v4tov4 listenaddress=$listenAddr listenport=$Port | Out-Null
            Write-Log "removed stale rule $name (LAN address is now $ip)"
        }
    }
    & netsh interface portproxy add v4tov4 listenaddress=$ip listenport=$Port connectaddress=$ConnectAddress connectport=$Port | Out-Null
    Write-Log "added rule $want -> $ConnectAddress/$Port"
    $changed = $true
}

# 3. The listener must actually be bound.
if ($changed) { Start-Sleep -Seconds 2 }
if (Test-Listener $ip) {
    if ($changed) { Write-Log "listener up on $want" }
    Write-Heartbeat "ok $want"
    exit 0
}
Write-Log "no listener on $want; restarting iphlpsvc"
# -Force stops dependents too (Tailscale, measured 2026-10-09); bring back any that were running.
$wasRunning = @((Get-Service iphlpsvc).DependentServices | Where-Object Status -eq 'Running' | ForEach-Object Name)
Restart-Service -Name iphlpsvc -Force
foreach ($svc in $wasRunning) {
    try { Start-Service -Name $svc; Write-Log "restarted dependent $svc" } catch { Write-Log "FAILED to restart dependent ${svc}: $_" }
}
for ($i = 0; $i -lt 10 -and -not (Test-Listener $ip); $i++) { Start-Sleep -Seconds 1 }
if (Test-Listener $ip) {
    Write-Log "listener up on $want after iphlpsvc restart"
    Write-Heartbeat "repaired $want"
    exit 0
}
Write-Log "STILL no listener on $want after iphlpsvc restart"
Write-Heartbeat "FAILED $want"
exit 1
