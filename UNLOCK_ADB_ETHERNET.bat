@echo off
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -NoProfile -Command "Start-Process cmd.exe -ArgumentList '/k \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)
cd /d "%~dp0"
call "%~dp0scripts\ensure-python.bat"
if %errorlevel% neq 0 exit /b 1

echo ==========================================================
echo Starting Jio STB Ethernet ADB Unlock Lab (Universal ACS)
echo ==========================================================
echo [*] If this tool helps you, please star our GitHub repo:
echo     https://github.com/krishnasen2401/jiostb
echo ==========================================================
echo.
echo Select your Jio STB Model Family:
echo   [1] SDMC / JMSD Series: JMSD200A / AirFiber (RILROOTCA cert) [DEFAULT]
echo   [2] JHS / Skyworth Series: JHSD200 / JHSC200 / JMSC200A / JHSB200 (eMudhra cert)
echo.
set MODEL_CHOICE=1
set /p MODEL_CHOICE="Enter choice [1 or 2, default 1]: "
set STB_MODEL=jms
if "%MODEL_CHOICE%"=="2" set STB_MODEL=jhs

if "%STB_MODEL%"=="jhs" (
    echo [+] Configured for JHS Series - eMudhra certificate chain
) else (
    echo [+] Configured for JMS Series - RILROOTCA certificate chain
)
echo.
echo [*] Tip: If STB never contacts the lab, temporarily turn OFF Windows Firewall
echo     (or pause Quick Heal/McAfee) as Windows drops incoming port 9443/8443 packets.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-adb-ethernet.ps1" -AcsScript "mock_acs_universal.py" -Model "%STB_MODEL%"
pause
