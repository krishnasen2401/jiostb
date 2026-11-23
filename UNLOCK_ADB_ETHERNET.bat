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
echo Select your Jio STB Unlock Mode:
echo   [1] Universal Auto-Detect: All Models (Auto-Switches eMudhra + RILROOTCA) [RECOMMENDED]
echo   [2] Pure Zero-401 Standalone: Bypass all Digest challenges (Direct Unlock for stubborn boxes)
echo   [3] Legacy Mode: Priority RILROOTCA chain (Skyworth / Older Builds)
echo.
set MODEL_CHOICE=1
set /p MODEL_CHOICE="Enter choice [1, 2, or 3, default 1]: "

if "%MODEL_CHOICE%"=="2" (
    echo.
    echo ==========================================================
    echo [+] Launching Standalone Zero-401 Lab over Ethernet...
    echo     - Direct 200 OK InformResponse (No 401 Digest challenges)
    echo     - Dual-Cert Auto-Fallback (eMudhra + RILROOTCA)
    echo     - 100%% Offline Standalone (No upstream relay dependencies)
    echo     - Supports all models: JHSD200, JHSC200, JMSD200, JMSC200
    echo ==========================================================
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-adb-ethernet.ps1" -AcsScript "mock_acs.py" -Model "universal"
    pause
    exit /b
)

set STB_MODEL=universal
if "%MODEL_CHOICE%"=="3" set STB_MODEL=legacy

if "%STB_MODEL%"=="universal" (
    echo [+] Configured for Universal Auto-Detect (Dual Auto-Switching eMudhra + RILROOTCA)
) else (
    echo [+] Configured for Legacy Priority (RILROOTCA chain with auto-fallback)
)
echo.
echo [*] Tip: If STB never contacts the lab, temporarily turn OFF Windows Firewall
echo     (or pause Quick Heal/McAfee) as Windows drops incoming port 9443/8443 packets.
echo.
echo [*] NOTE: No Factory Reset is required! The lab provisions both un-reset
echo     and freshly reset boxes seamlessly with automatic certificate failover.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-adb-ethernet.ps1" -AcsScript "mock_acs_universal.py" -Model "%STB_MODEL%"
pause
