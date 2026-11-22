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
echo Starting Jio STB Wi-Fi Hotspot ADB Unlock Lab (Universal)
echo ==========================================================
echo [*] If this tool helps you, please star our GitHub repo:
echo     https://github.com/krishnasen2401/jiostb
echo ==========================================================
echo.
echo Select your Jio STB Unlock Mode:
echo   [1] Universal Auto-Select: All Models (JHSD, JHSC, JMSC, JMSD, JMSB, AirFiber) [DEFAULT]
echo   [2] Original Zero-401 Lab: Verified Initial Release (Zero 401 Challenge / Launches original_repo)
echo   [3] Legacy / Custom: Fallback RILROOTCA Chain
echo.
set MODEL_CHOICE=1
set /p MODEL_CHOICE="Enter choice [1, 2, or 3, default 1]: "

if "%MODEL_CHOICE%"=="2" (
    echo.
    echo ==========================================================
    echo [+] Launching Original Zero-401 Lab over Wi-Fi Hotspot...
    echo     - Direct 200 OK InformResponse (No 401 Digest challenges)
    echo     - 100%% Offline Standalone (No upstream relay dependencies)
    echo     - Supports all models: JHSD200, JHSC200, JMSD200, JMSC200
    echo ==========================================================
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-adb-wifi.ps1" -AcsScript "mock_acs.py" -Model "universal"
    pause
    exit /b
)

set STB_MODEL=universal
if "%MODEL_CHOICE%"=="3" set STB_MODEL=legacy

if "%STB_MODEL%"=="universal" (
    echo [+] Configured for Universal Auto-Select - Verified eMudhra TLS chain (Comodo AAA CA)
) else (
    echo [+] Configured for Legacy - RILROOTCA certificate chain
)
echo.
echo [*] Tip: If STB never contacts the lab, temporarily turn OFF Windows Firewall
echo     (or pause Quick Heal/McAfee) as Windows drops incoming port 9443/8443 packets.
echo.
echo [*] PRO-TIP: If STB loops on /generate_204 or fails TLS (CERTIFICATE_UNKNOWN),
echo     perform a FACTORY RESET on the STB (Settings -> Device Preferences -> Reset).
echo     During fresh setup, the STB forces immediate TR-069 provisioning without backoff!
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-adb-wifi.ps1" -AcsScript "mock_acs_universal.py" -Model "%STB_MODEL%"
pause
