#Requires -RunAsAdministrator
param(
    [string]$AcsScript = 'mock_acs_universal.py',
    [string]$Model = 'jms'
)
$ErrorActionPreference = 'Continue'
$base = Split-Path -Parent $PSScriptRoot
$labAddress = '192.168.137.1'
$labPrefix = 24

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "       JIO STB WI-FI HOTSPOT CAPTIVE LAB INITIALIZER       " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Clean up lingering lab / mock ACS processes
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
        ($_.CommandLine -like "*captive_wifi_lab*" -or $_.CommandLine -like "*mock_acs*")
    } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
} catch {}
@('captive-wifi-lab.pid', 'captive-lab.pid') | ForEach-Object {
    $pidFile = Join-Path $base $_
    if (Test-Path $pidFile) {
        $oldPid = Get-Content $pidFile -ErrorAction SilentlyContinue
        if ($oldPid) { Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
}

# 2. Stop w32time so our NTP server can bind to UDP 123
Write-Host "[2/5] Stopping Windows Time Service (w32time) for Port 123..." -ForegroundColor Yellow
Stop-Service w32time -ErrorAction SilentlyContinue

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
    Write-Host "    3. Re-run this Wi-Fi unlock script." -ForegroundColor Cyan
    Write-Host "==========================================================`n" -ForegroundColor Yellow
}

# 3. Configure Virtual Hotspot / Hosted Network
Write-Host "[3/5] Checking Wi-Fi Hotspot configuration..." -ForegroundColor Yellow

# Check if Windows Mobile Hotspot or an adapter with 192.168.137.1 is already up
$existingHotspot = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -eq $labAddress }

if (-not $existingHotspot) {
    # Attempt to start hostednetwork via netsh (for USB/Wi-Fi adapters with hostednetwork support)
    & netsh.exe wlan set hostednetwork mode=allow ssid="JioSTB-Setup" key="password123" | Out-Null
    & netsh.exe wlan start hostednetwork | Out-Null
    Start-Sleep -Seconds 2
}

# Detect hotspot adapter
$hotspotAdapter = Get-NetAdapter | Where-Object { 
    $_.InterfaceDescription -like "*Hosted Network*" -or 
    $_.InterfaceDescription -like "*Wi-Fi Direct*" -or
    $_.Name -like "Local Area Connection*" -or
    $_.Name -eq "Wi-Fi 2"
} | Select-Object -First 1

# If not found by name, check by IP 192.168.137.1
if (-not $hotspotAdapter) {
    $ipEntry = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -eq $labAddress }
    if ($ipEntry) {
        $hotspotAdapter = Get-NetAdapter -InterfaceIndex $ipEntry.InterfaceIndex -ErrorAction SilentlyContinue
    }
}

if (-not $hotspotAdapter) {
    Write-Host "[!] Note: Could not find an active Wi-Fi Hotspot adapter automatically." -ForegroundColor Yellow
    Write-Host "    If you are using Windows Mobile Hotspot:" -ForegroundColor Cyan
    Write-Host "    1. Open Windows Settings -> Network & internet -> Mobile hotspot" -ForegroundColor Cyan
    Write-Host "    2. Toggle Mobile hotspot to ON (SSID: JioSTB-Setup, Pass: password123)" -ForegroundColor Cyan
    Write-Host "    * Windows 11 Tip: Windows requires an active internet connection to enable Hotspot." -ForegroundColor DarkYellow
    Write-Host "      (Workaround: Connect PC to phone hotspot first, turn Mobile Hotspot ON, then proceed)" -ForegroundColor DarkYellow
    Write-Host "    * HP Victus / AMD / MediaTek MT7921 Tip: If Wi-Fi loops ON/OFF, use Direct Ethernet!" -ForegroundColor DarkYellow
    Write-Host "    The server will still bind to 0.0.0.0 and listen for connections!`n" -ForegroundColor Yellow
} else {
    Write-Host "[+] Found Hotspot Adapter: $($hotspotAdapter.Name) ($($hotspotAdapter.InterfaceDescription))" -ForegroundColor Green
    
    # Configure 192.168.137.1 if not present
    $currentIPs = (Get-NetIPAddress -InterfaceIndex $hotspotAdapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress
    if ($currentIPs -notcontains $labAddress) {
        New-NetIPAddress -InterfaceIndex $hotspotAdapter.ifIndex -IPAddress $labAddress -PrefixLength $labPrefix -ErrorAction SilentlyContinue | Out-Null
    }
    
    # Add Aliases so requests to Jio ACS & Google connectivity checks land on PC
    @('8.8.8.8', '142.250.190.46', '49.44.112.10') | ForEach-Object {
        if ($currentIPs -notcontains $_) {
            New-NetIPAddress -InterfaceIndex $hotspotAdapter.ifIndex -IPAddress $_ -PrefixLength 32 -ErrorAction SilentlyContinue | Out-Null
        }
    }
}

# 4. Configure Windows Firewall
Write-Host "[4/5] Updating Windows Firewall rules for Wi-Fi Lab..." -ForegroundColor Yellow
Get-NetFirewallRule -DisplayName 'LocalLab-WifiHotspot*' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -DisplayName 'Block 443 Noise' -ErrorAction SilentlyContinue | Remove-NetFirewallRule

New-NetFirewallRule -DisplayName 'LocalLab-WifiHotspot-Allow-UDP' -Group 'LocalLab-WifiHotspot' -Direction Inbound -Action Allow -Protocol UDP -LocalPort 53,67,123 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'LocalLab-WifiHotspot-Allow-TCP' -Group 'LocalLab-WifiHotspot' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 53,80,7443,7547,8080,8443,9443 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'LocalLab-WifiHotspot-Block-Port443' -Group 'LocalLab-WifiHotspot' -Direction Inbound -Action Block -Protocol TCP -LocalPort 443 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'LocalLab-WifiHotspot-Allow-ICMP' -Group 'LocalLab-WifiHotspot' -Direction Inbound -Action Allow -Protocol ICMPv4 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null

# 5. Launch Servers
Write-Host "[5/5] Launching Mock ACS Server ($AcsScript) and Captive Lab..." -ForegroundColor Green
$python = (Get-Command python -ErrorAction Stop).Source
$env:CAPTIVE_BIND_IP = '0.0.0.0'

$env:STB_MODEL = $Model
# Start selected mock ACS script in a separate console window so logs are clearly visible
Start-Process -FilePath (Join-Path $base 'scripts\run-acs-window.bat') -ArgumentList "$AcsScript --model $Model" -WorkingDirectory $base

Write-Host "`n>>> Starting captive_wifi_lab.py..." -ForegroundColor Cyan
& $python (Join-Path $base 'captive_wifi_lab.py')
