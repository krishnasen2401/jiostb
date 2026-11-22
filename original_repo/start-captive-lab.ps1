#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$base = $PSScriptRoot
$adapterName = 'Ethernet'
$labAddress = '192.168.50.1'
$labPrefix = 24

Write-Host "Cleaning up lingering lab / mock ACS processes..."
Get-NetTCPConnection -LocalPort 7443,8443,9443 -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}
if (Test-Path (Join-Path $base 'captive-lab.pid')) {
    $oldPid = Get-Content (Join-Path $base 'captive-lab.pid') -ErrorAction SilentlyContinue
    if ($oldPid) { Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue }
    Remove-Item (Join-Path $base 'captive-lab.pid') -Force -ErrorAction SilentlyContinue
}

Write-Host "Stopping Windows Time Service (w32time) to free Port 123..."
Stop-Service w32time -Force -ErrorAction SilentlyContinue
& net.exe stop w32time /y 2>$null | Out-Null
Start-Sleep -Seconds 1

$adapter = Get-NetAdapter -Name $adapterName -ErrorAction Stop
Set-NetIPInterface -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -Forwarding Disabled
Set-NetIPInterface -InterfaceIndex $adapter.ifIndex -AddressFamily IPv6 -Forwarding Disabled
& netsh.exe interface portproxy reset | Out-Null
Get-NetRoute -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -ne '127.0.0.1' } | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
Set-NetIPInterface -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -Dhcp Disabled

New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress $labAddress -PrefixLength $labPrefix | Out-Null
New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress '8.8.8.8' -PrefixLength 32 | Out-Null
New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress '142.250.190.46' -PrefixLength 32 | Out-Null
New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress '49.44.112.10' -PrefixLength 32 | Out-Null
Start-Sleep -Seconds 2

Get-NetFirewallRule -DisplayName 'LocalLab-Allow-Inbound*' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -DisplayName 'LocalLab-Isolate-Subnet' -ErrorAction SilentlyContinue | Remove-NetFirewallRule

New-NetFirewallRule -DisplayName 'LocalLab-Allow-Inbound-UDP' -Group 'LocalLab' -Direction Inbound -Action Allow -Protocol UDP -LocalPort 53,67,123 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'LocalLab-Allow-Inbound-TCP' -Group 'LocalLab' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 53,80,7443,8080,8443,9443 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'LocalLab-Allow-Inbound-ICMP' -Group 'LocalLab' -Direction Inbound -Action Allow -Protocol ICMPv4 -LocalAddress Any -RemoteAddress Any -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'LocalLab-Isolate-Subnet' -Group 'LocalLab' -Direction Outbound -Action Block -Protocol Any -LocalAddress '192.168.50.0/24','49.44.112.10','142.250.190.46' -RemoteAddress '0.0.0.0-192.168.49.255','192.168.51.0-255.255.255.255' -Profile Any | Out-Null

$python = (Get-Command python -ErrorAction Stop).Source
$env:CAPTIVE_BIND_IP = '0.0.0.0'
Write-Host "Starting Mock ACS Server (mock_acs.py)..."
Start-Process -FilePath $python -ArgumentList (Join-Path $base 'mock_acs.py') -WorkingDirectory $base
Write-Host "Starting isolated captive lab (captive_lab.py) on '$adapterName' at $labAddress"
& $python (Join-Path $base 'captive_lab.py')
