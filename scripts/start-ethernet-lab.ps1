#Requires -RunAsAdministrator
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

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "       JIO STB FOTA & TR-069 ETHERNET RESEARCH LAB         " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Clean up old processes & ports
Write-Host "`n[1/5] Cleaning up old processes & freeing ports..." -ForegroundColor Yellow
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
        ($_.CommandLine -like "*fota_captive*" -or $_.CommandLine -like "*captive_lab*" -or $_.CommandLine -like "*mock_acs*")
    } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
} catch {}

@('fota-lab.pid', 'captive-lab.pid') | ForEach-Object {
    $pidFile = Join-Path $base $_
    if (Test-Path $pidFile) {
        $oldPid = Get-Content $pidFile -ErrorAction SilentlyContinue
        if ($oldPid) { Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
}

# 2. Stop w32time for NTP port 123 & SharedAccess for DNS port 53
Write-Host "[2/5] Stopping Windows Time Service (w32time)..." -ForegroundColor Yellow
Stop-Service w32time -ErrorAction SilentlyContinue

Write-Host "      Stopping Windows Mobile Hotspot / ICS service (SharedAccess)..." -ForegroundColor Yellow
Stop-Service -Name "SharedAccess" -Force -ErrorAction SilentlyContinue

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
    Write-Host "    3. Re-run this lab script." -ForegroundColor Cyan
    Write-Host "==========================================================`n" -ForegroundColor Yellow
}

# 3. Configure Ethernet Interface (with USB-to-Ethernet support)
Write-Host "[3/5] Detecting Ethernet / USB-to-Ethernet Adapter..." -ForegroundColor Yellow
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
Write-Host "[+] Configuring Adapter: $adapterName ($($adapter.InterfaceDescription)) to $labAddress..." -ForegroundColor Green

if ($adapter) {
    Set-NetIPInterface -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -Forwarding Disabled -ErrorAction SilentlyContinue
    Set-NetIPInterface -InterfaceIndex $adapter.ifIndex -AddressFamily IPv6 -Forwarding Disabled -ErrorAction SilentlyContinue
    & netsh.exe interface portproxy reset | Out-Null
    Get-NetRoute -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
    Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -ne '127.0.0.1' } | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
    Set-NetIPInterface -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -Dhcp Disabled -ErrorAction SilentlyContinue

    New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress $labAddress -PrefixLength $labPrefix -ErrorAction SilentlyContinue | Out-Null
    New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress '8.8.8.8' -PrefixLength 32 -ErrorAction SilentlyContinue | Out-Null
    New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress '142.250.190.46' -PrefixLength 32 -ErrorAction SilentlyContinue | Out-Null
    New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress '49.44.112.10' -PrefixLength 32 -ErrorAction SilentlyContinue | Out-Null
} else {
    Write-Host "[!] Warning: Ethernet adapter not found. Binding to local sockets only." -ForegroundColor Yellow
}

# 4. Windows Firewall Rules
Write-Host "[4/5] Updating Windows Firewall rules for Lab..." -ForegroundColor Yellow
Get-NetFirewallRule -DisplayName 'Jio-FOTA-Lab*' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -DisplayName 'Block 443 Noise' -ErrorAction SilentlyContinue | Remove-NetFirewallRule

New-NetFirewallRule -DisplayName 'Jio-FOTA-Lab-Allow-UDP' -Group 'Jio-FOTA-Lab' -Direction Inbound -Action Allow -Protocol UDP -LocalPort 53,67,123 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'Jio-FOTA-Lab-Allow-TCP' -Group 'Jio-FOTA-Lab' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 53,80,7443,7547,8080,8443,9443 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'Jio-FOTA-Lab-Block-Port443' -Group 'Jio-FOTA-Lab' -Direction Inbound -Action Block -Protocol TCP -LocalPort 443 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'Jio-FOTA-Lab-Allow-ICMP' -Group 'Jio-FOTA-Lab' -Direction Inbound -Action Allow -Protocol ICMPv4 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null

# 5. Launch Services
Write-Host "[5/5] Launching FOTA Monitor ACS and Captive Responder..." -ForegroundColor Green
$python = (Get-Command python -ErrorAction Stop).Source

# Start monitor ACS in a separate console window for live logging
Start-Process -FilePath $python -ArgumentList (Join-Path $base 'fota_monitor_acs.py') -WorkingDirectory $base

Write-Host "`n>>> Starting Universal Captive Responder on Ethernet..." -ForegroundColor Cyan
& $python (Join-Path $base 'fota_captive_lab.py') --mode ethernet
