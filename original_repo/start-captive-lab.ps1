
#Requires -RunAsAdministrator

$ErrorActionPreference = 'Stop'

$base       = $PSScriptRoot
$labAddress = '192.168.50.1'
$labPrefix  = 24

# ============================================================
# 1. AUTOMATIC ETHERNET ADAPTER DETECTION
# ============================================================

Write-Host "`nDetecting connected physical Ethernet adapters..." -ForegroundColor Cyan

$adapters = @(
    Get-NetAdapter -Physical | Where-Object {
        $_.Status -eq 'Up' -and
        $_.HardwareInterface -eq $true -and
        $_.InterfaceDescription -notmatch 'Wi-Fi|Wireless|Bluetooth'
    }
)

if ($adapters.Count -eq 0) {
    throw "No connected physical Ethernet adapter found. Connect your USB Ethernet adapter and retry."
}

if ($adapters.Count -gt 1) {
    Write-Host "`nMultiple connected Ethernet adapters detected:" -ForegroundColor Yellow

    $adapters | Format-Table Name, InterfaceDescription, MacAddress, LinkSpeed -AutoSize

    throw "Multiple Ethernet adapters detected. Disconnect unused adapters and retry."
}

$adapter = $adapters[0]
$adapterName = $adapter.Name

Write-Host "`nSelected adapter: $adapterName" -ForegroundColor Green
Write-Host "Description: $($adapter.InterfaceDescription)"
Write-Host "MAC Address: $($adapter.MacAddress)"
Write-Host "Interface Index: $($adapter.ifIndex)"

# ============================================================
# 2. CLEANUP EXISTING LAB PROCESSES
# ============================================================

Write-Host "`nCleaning up lingering lab / mock ACS processes..." -ForegroundColor Cyan

Get-NetTCPConnection -LocalPort 7443,8443,9443 -ErrorAction SilentlyContinue |
    ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }

$pidFile = Join-Path $base 'captive-lab.pid'

if (Test-Path $pidFile) {
    $oldPid = Get-Content $pidFile -ErrorAction SilentlyContinue

    if ($oldPid) {
        Stop-Process -Id ([int]$oldPid) -Force -ErrorAction SilentlyContinue
    }

    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# ============================================================
# 3. FREE PORT 123
# ============================================================

Write-Host "`nStopping Windows Time Service (w32time) to free Port 123..." -ForegroundColor Cyan

Stop-Service w32time -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# ============================================================
# 4. NETWORK INTERFACE CONFIGURATION
# ============================================================

Write-Host "`nConfiguring isolated STB network..." -ForegroundColor Cyan

Set-NetIPInterface -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -Forwarding Disabled
Set-NetIPInterface -InterfaceIndex $adapter.ifIndex -AddressFamily IPv6 -Forwarding Disabled

# Reset existing port proxy rules
& netsh.exe interface portproxy reset | Out-Null

# Remove default IPv4 routes from selected adapter
Get-NetRoute -InterfaceIndex $adapter.ifIndex `
    -AddressFamily IPv4 `
    -DestinationPrefix '0.0.0.0/0' `
    -ErrorAction SilentlyContinue |
    Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue

# Remove existing IPv4 addresses
Get-NetIPAddress -InterfaceIndex $adapter.ifIndex `
    -AddressFamily IPv4 `
    -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPAddress -ne '127.0.0.1'
    } |
    Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue

# Disable DHCP on the lab adapter
Set-NetIPInterface -InterfaceIndex $adapter.ifIndex `
    -AddressFamily IPv4 `
    -Dhcp Disabled

# Assign lab IP
New-NetIPAddress -InterfaceIndex $adapter.ifIndex `
    -IPAddress $labAddress `
    -PrefixLength $labPrefix | Out-Null

# Assign host aliases used by the captive lab
New-NetIPAddress -InterfaceIndex $adapter.ifIndex `
    -IPAddress '8.8.8.8' `
    -PrefixLength 32 | Out-Null

New-NetIPAddress -InterfaceIndex $adapter.ifIndex `
    -IPAddress '142.250.190.46' `
    -PrefixLength 32 | Out-Null

New-NetIPAddress -InterfaceIndex $adapter.ifIndex `
    -IPAddress '49.44.112.10' `
    -PrefixLength 32 | Out-Null

Start-Sleep -Seconds 2

# ============================================================
# 5. FIREWALL CONFIGURATION
# ============================================================

Write-Host "`nConfiguring lab firewall rules..." -ForegroundColor Cyan

Get-NetFirewallRule -DisplayName 'LocalLab-Allow-Inbound*' `
    -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule

Get-NetFirewallRule -DisplayName 'LocalLab-Isolate-Subnet' `
    -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule

# Allow inbound UDP services
New-NetFirewallRule `
    -DisplayName 'LocalLab-Allow-Inbound-UDP' `
    -Group 'LocalLab' `
    -Direction Inbound `
    -Action Allow `
    -Protocol UDP `
    -LocalPort 53,67,123 `
    -LocalAddress Any `
    -RemoteAddress Any `
    -Profile Any | Out-Null

# Allow inbound TCP services
New-NetFirewallRule `
    -DisplayName 'LocalLab-Allow-Inbound-TCP' `
    -Group 'LocalLab' `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 53,80,7443,8080,8443,9443 `
    -LocalAddress Any `
    -RemoteAddress Any `
    -Profile Any | Out-Null

# Allow ICMP
New-NetFirewallRule `
    -DisplayName 'LocalLab-Allow-Inbound-ICMP' `
    -Group 'LocalLab' `
    -Direction Inbound `
    -Action Allow `
    -Protocol ICMPv4 `
    -LocalAddress Any `
    -RemoteAddress Any `
    -Profile Any | Out-Null

# Isolate lab subnet from external networks
New-NetFirewallRule `
    -DisplayName 'LocalLab-Isolate-Subnet' `
    -Group 'LocalLab' `
    -Direction Outbound `
    -Action Block `
    -Protocol Any `
    -LocalAddress '192.168.50.0/24','49.44.112.10','142.250.190.46' `
    -RemoteAddress '0.0.0.0-192.168.49.255','192.168.51.0-255.255.255.255' `
    -Profile Any | Out-Null

# ============================================================
# 6. START MOCK ACS SERVER
# ============================================================

$python = (Get-Command python -ErrorAction Stop).Source

$env:CAPTIVE_BIND_IP = '0.0.0.0'

Write-Host "`nStarting Mock ACS Server (mock_acs.py)..." -ForegroundColor Green

$acsScript = Join-Path $base 'mock_acs.py'

if (-not (Test-Path $acsScript)) {
    throw "mock_acs.py not found: $acsScript"
}

Start-Process -FilePath $python `
    -ArgumentList "`"$acsScript`"" `
    -WorkingDirectory $base

# ============================================================
# 7. START CAPTIVE LAB
# ============================================================

$captiveScript = Join-Path $base 'captive_lab.py'

if (-not (Test-Path $captiveScript)) {
    throw "captive_lab.py not found: $captiveScript"
}

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " JIO STB ISOLATED CAPTIVE LAB" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host " Adapter      : $adapterName"
Write-Host " Lab IP       : $labAddress"
Write-Host " Subnet       : 192.168.50.0/24"
Write-Host " Mock ACS     : Running separately"
Write-Host " Captive Lab  : Starting..."
Write-Host "==========================================================" -ForegroundColor Green

& $python $captiveScript

