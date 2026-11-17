#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $PSScriptRoot
$adapterName = '*Wi-Fi*'
$labAddress = '192.168.137.1'

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "     JIO STB FOTA & TR-069 WI-FI HOTSPOT RESEARCH LAB      " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Clean up old processes & ports
Write-Host "`n[1/4] Cleaning up old processes & freeing ports..." -ForegroundColor Yellow
Get-NetUDPEndpoint -LocalPort 53,67,123 -ErrorAction SilentlyContinue | ForEach-Object {
    $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    if ($proc.ProcessName -like "*python*") {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}
Get-NetTCPConnection -LocalPort 53,80,443,7443,8443,9443 -ErrorAction SilentlyContinue | ForEach-Object {
    $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    if ($proc.ProcessName -like "*python*") {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { 
    $_.Name -like "*python*" -and 
    $_.ProcessId -ne $PID -and 
    ($_.CommandLine -like "*captive_wifi_lab*" -or $_.CommandLine -like "*mock_acs*")
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

# 2. Virtual IP on Hotspot Interface
Write-Host "[2/4] Setting up Fake ACS IP Aliases on Hotspot..." -ForegroundColor Yellow
$hotspotAdapter = Get-NetAdapter | Where-Object { $_.InterfaceDescription -match 'Direct Virtual|Microsoft Wi-Fi Direct' -or $_.Name -match 'Local Area Connection\*' } | Select-Object -First 1

if ($hotspotAdapter) {
    New-NetIPAddress -InterfaceIndex $hotspotAdapter.ifIndex -IPAddress '49.44.112.10' -PrefixLength 32 -ErrorAction SilentlyContinue | Out-Null
    New-NetIPAddress -InterfaceIndex $hotspotAdapter.ifIndex -IPAddress '142.250.190.46' -PrefixLength 32 -ErrorAction SilentlyContinue | Out-Null
    Write-Host "[+] Virtual IP aliases configured on: $($hotspotAdapter.Name)" -ForegroundColor Green
} else {
    Write-Host "[!] Note: Enable Windows Mobile Hotspot in Windows Settings before running if not already active." -ForegroundColor Yellow
}

# 3. Windows Firewall Rules
Write-Host "[3/4] Updating Windows Firewall rules..." -ForegroundColor Yellow
Get-NetFirewallRule -DisplayName 'Jio-FOTA-Lab*' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -DisplayName 'Block 443 Noise' -ErrorAction SilentlyContinue | Remove-NetFirewallRule

New-NetFirewallRule -DisplayName 'Jio-FOTA-Lab-Allow-UDP' -Group 'Jio-FOTA-Lab' -Direction Inbound -Action Allow -Protocol UDP -LocalPort 53,67,123 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'Jio-FOTA-Lab-Allow-TCP' -Group 'Jio-FOTA-Lab' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 53,80,7443,7547,8080,8443,9443 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'Jio-FOTA-Lab-Block-Port443' -Group 'Jio-FOTA-Lab' -Direction Inbound -Action Block -Protocol TCP -LocalPort 443 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null

# 4. Launch Services
Write-Host "[4/4] Launching FOTA Monitor ACS and Captive Responder..." -ForegroundColor Green
$python = (Get-Command python -ErrorAction Stop).Source

Start-Process -FilePath $python -ArgumentList (Join-Path $base 'fota_monitor_acs.py') -WorkingDirectory $base

Write-Host "`n>>> Starting Universal Captive Responder on Wi-Fi Hotspot..." -ForegroundColor Cyan
& $python (Join-Path $base 'fota_captive_lab.py') --mode wifi
