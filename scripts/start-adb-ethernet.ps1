#Requires -RunAsAdministrator
param(
    [string]$AcsScript = 'mock_acs_universal.py',
    [string]$Model = 'jms'
)
$ErrorActionPreference = 'Continue'
if (-not $PSScriptRoot) {
    $PSScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
}
if (-not $PSScriptRoot) {
    $PSScriptRoot = (Get-Location).Path
}
$base = Split-Path -Parent $PSScriptRoot
if (-not $base -or -not (Test-Path $base)) {
    $base = (Get-Location).Path
}
$adapterName = 'Ethernet'
$labAddress = '192.168.50.1'
$labPrefix = 24

Write-Host "Cleaning up lingering lab / mock ACS processes..."
try {
    # Free UDP ports (DNS=53, DHCP=67, NTP=123)
    Get-NetUDPEndpoint -LocalPort 53,67,123 -ErrorAction SilentlyContinue | ForEach-Object {
        $pId = $_.OwningProcess
        if ($pId -and $pId -gt 4) {
            $proc = Get-Process -Id $pId -ErrorAction SilentlyContinue
            if ($proc -and $proc.ProcessName -like "*python*") {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
} catch {}

try {
    # Free TCP ports
    Get-NetTCPConnection -LocalPort 53,80,443,7443,7547,8080,8443,9443 -ErrorAction SilentlyContinue | ForEach-Object {
        $pId = $_.OwningProcess
        if ($pId -and $pId -gt 4) {
            $proc = Get-Process -Id $pId -ErrorAction SilentlyContinue
            if ($proc -and $proc.ProcessName -like "*python*") {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
} catch {}

try {
    # Stop orphaned Python lab instances (strictly filter for python and exclude our own PID)
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { 
        $_.Name -like "*python*" -and 
        $_.ProcessId -ne $PID -and 
        ($_.CommandLine -like "*captive_lab*" -or $_.CommandLine -like "*mock_acs*" -or $_.CommandLine -like "*fota_captive*")
    } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
} catch {}

if (Test-Path (Join-Path $base 'captive-lab.pid')) {
    $oldPid = Get-Content (Join-Path $base 'captive-lab.pid') -ErrorAction SilentlyContinue
    if ($oldPid) { Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue }
    Remove-Item (Join-Path $base 'captive-lab.pid') -Force -ErrorAction SilentlyContinue
}

Write-Host "Stopping Windows Time Service (w32time) to free Port 123..."
Stop-Service w32time -ErrorAction SilentlyContinue

Write-Host "Stopping Windows Mobile Hotspot / ICS service (SharedAccess) to free Port 53..."
Stop-Service -Name "SharedAccess" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# Quick Heal / Antivirus Firewall check
$qhProcesses = Get-Process -Name "*quickheal*", "*qh*", "*onlinent*", "*sclnt*" -ErrorAction SilentlyContinue
$qhServices = Get-Service -Name "*quickheal*", "*qh*" -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Running' }
if ($qhProcesses -or $qhServices) {
    $detectedName = if ($qhProcesses) { $qhProcesses[0].ProcessName } else { $qhServices[0].Name }
    Write-Host ""
    Write-Host "==========================================================" -ForegroundColor Yellow
    Write-Host "[!] Quick Heal Antivirus / Firewall detected ($detectedName)" -ForegroundColor Yellow
    Write-Host "    Quick Heal blocks Python from binding DNS Port 53 (WinError 10013)." -ForegroundColor Yellow
    Write-Host "    TO RESOLVE (2 clicks):" -ForegroundColor Cyan
    Write-Host "    1. Right-click the green 'Q' Quick Heal icon in the taskbar tray." -ForegroundColor Cyan
    Write-Host "    2. Click 'Pause Protection' -> Select '15 minutes' (or 30 mins)." -ForegroundColor Cyan
    Write-Host "    3. Re-run this unlock script." -ForegroundColor Cyan
    Write-Host "==========================================================`n" -ForegroundColor Yellow
}

# Detect Ethernet / USB-to-Ethernet Adapter
Write-Host "Detecting Ethernet / USB-to-Ethernet Adapter..."
$adapter = $null

$allEthernetAdapters = @(Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
    $_.PhysicalMediaType -ne 'Native 802.11' -and
    $_.PhysicalMediaType -ne 'BlueTooth' -and
    $_.MediaType -ne 'Native 802.11' -and
    $_.InterfaceDescription -notmatch 'Virtual|Hyper-V|Loopback|TAP|VPN|Host-Only|Bluetooth|Wi-Fi|Wireless|Direct|Tunnel|Tailscale' -and
    $_.Status -ne 'Disabled'
})

if ($allEthernetAdapters.Count -eq 0) {
    Write-Host "[!] ERROR: No wired or USB-to-Ethernet adapter found!" -ForegroundColor Red
    Write-Host "    Please connect your USB-to-Ethernet adapter or Ethernet cable and re-run." -ForegroundColor Yellow
    Read-Host "Press Enter to exit..."
    exit 1
} elseif ($allEthernetAdapters.Count -eq 1) {
    $adapter = $allEthernetAdapters[0]
    Write-Host "[+] Automatically selected Ethernet Adapter: $($adapter.Name) ($($adapter.InterfaceDescription)) - Status: $($adapter.Status)" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host "Multiple Ethernet adapters detected ($($allEthernetAdapters.Count) found):" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan
    
    # Priority: Prefer adapter that has a cable plugged in (Status == 'Up')
    $defaultIdx = 0
    for ($i = 0; $i -lt $allEthernetAdapters.Count; $i++) {
        if ($allEthernetAdapters[$i].Status -eq 'Up') {
            $defaultIdx = $i
            break
        } elseif ($allEthernetAdapters[$i].InterfaceDescription -match 'USB|AX88|RTL815|ASIX|Dongle') {
            $defaultIdx = $i
        }
    }
    
    for ($i = 0; $i -lt $allEthernetAdapters.Count; $i++) {
        $a = $allEthernetAdapters[$i]
        $rec = if ($i -eq $defaultIdx) { " [RECOMMENDED]" } else { "" }
        $stat = if ($a.Status -eq 'Up') { "Up (Cable Connected)" } else { $a.Status }
        Write-Host "  [$($i+1)] $($a.Name) ($($a.InterfaceDescription)) - $stat$rec"
    }
    Write-Host ""
    $prompt = "Select adapter connected to your Jio STB [1-$($allEthernetAdapters.Count), default $($defaultIdx+1)]: "
    $choice = Read-Host $prompt
    if (-not $choice -or -not ($choice -match '^\d+$')) {
        $adapter = $allEthernetAdapters[$defaultIdx]
    } else {
        $sel = [int]$choice - 1
        if ($sel -ge 0 -and $sel -lt $allEthernetAdapters.Count) {
            $adapter = $allEthernetAdapters[$sel]
        } else {
            $adapter = $allEthernetAdapters[$defaultIdx]
        }
    }
    Write-Host "[+] Selected Ethernet Adapter: $($adapter.Name) ($($adapter.InterfaceDescription))`n" -ForegroundColor Green
}

$adapterName = $adapter.Name
Write-Host "[+] Using Ethernet Adapter: $adapterName ($($adapter.InterfaceDescription))" -ForegroundColor Green
Set-NetIPInterface -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -Forwarding Disabled
Set-NetIPInterface -InterfaceIndex $adapter.ifIndex -AddressFamily IPv6 -Forwarding Disabled
& netsh.exe interface portproxy reset | Out-Null
Get-NetRoute -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -ne '127.0.0.1' } | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
Set-NetIPInterface -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -Dhcp Disabled

New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress $labAddress -PrefixLength $labPrefix -ErrorAction SilentlyContinue | Out-Null
New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress '8.8.8.8' -PrefixLength 32 -ErrorAction SilentlyContinue | Out-Null
New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress '142.250.190.46' -PrefixLength 32 -ErrorAction SilentlyContinue | Out-Null
New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress '49.44.112.10' -PrefixLength 32 -ErrorAction SilentlyContinue | Out-Null
Start-Sleep -Seconds 2

Get-NetFirewallRule -DisplayName 'LocalLab-Allow-Inbound*' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -DisplayName 'LocalLab-Isolate-Subnet' -ErrorAction SilentlyContinue | Remove-NetFirewallRule

New-NetFirewallRule -DisplayName 'LocalLab-Allow-Inbound-UDP' -Group 'LocalLab' -Direction Inbound -Action Allow -Protocol UDP -LocalPort 53,67,123 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'LocalLab-Allow-Inbound-TCP' -Group 'LocalLab' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 53,80,443,7443,7547,8080,8443,9443 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'LocalLab-Allow-Inbound-ICMP' -Group 'LocalLab' -Direction Inbound -Action Allow -Protocol ICMPv4 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'LocalLab-Isolate-Subnet' -Group 'LocalLab' -Direction Outbound -Action Block -Protocol Any -LocalAddress '192.168.50.0/24','49.44.112.10','142.250.190.46' -RemoteAddress '0.0.0.0-192.168.49.255','192.168.51.0-255.255.255.255' -Profile Any | Out-Null

$env:STB_MODEL = $Model
$python = (Get-Command python -ErrorAction Stop).Source
$env:CAPTIVE_BIND_IP = '0.0.0.0'
Write-Host "Starting Mock ACS Server ($AcsScript --model $Model)..."
Start-Process -FilePath (Join-Path $base 'scripts\run-acs-window.bat') -ArgumentList "$AcsScript --model $Model" -WorkingDirectory $base
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ">>> ACTION: POWER-CYCLE (REBOOT) THE JIO STB NOW! <<<" -ForegroundColor Yellow
Write-Host "1. Unplug the power cable from the back of the STB." -ForegroundColor Cyan
Write-Host "2. Connect Ethernet cable between PC and STB." -ForegroundColor Cyan
Write-Host "3. Plug power back in. The STB TR-069 client only connects on boot!" -ForegroundColor Cyan
Write-Host "==========================================================`n" -ForegroundColor Green
Write-Host "Starting isolated captive lab (captive_lab.py) on '$adapterName' at $labAddress"
& $python (Join-Path $base 'captive_lab.py')
