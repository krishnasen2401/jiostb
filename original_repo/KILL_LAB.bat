@echo off
net session >nul 2>&1
if %errorLevel% neq 0 (
    powershell -NoProfile -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo Cleaning up captive lab and mock ACS processes...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 7443,8443,9443 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
powershell -NoProfile -Command "Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like '*mock_acs*' -or $_.MainWindowTitle -like '*captive_lab*' } | Stop-Process -Force -ErrorAction SilentlyContinue"
powershell -NoProfile -Command "if (Test-Path 'C:\Users\krishnasen\Downloads\captive-lab.pid') { Remove-Item 'C:\Users\krishnasen\Downloads\captive-lab.pid' -Force }"

echo Restarting Windows Time service...
powershell -NoProfile -Command "Start-Service w32time -ErrorAction SilentlyContinue"

echo Cleanup complete.
timeout /t 2 >nul
