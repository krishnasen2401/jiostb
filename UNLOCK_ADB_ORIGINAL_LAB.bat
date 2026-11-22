@echo off
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -NoProfile -Command "Start-Process cmd.exe -ArgumentList '/k \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)
cd /d "%~dp0original_repo"
echo ==========================================================
echo Starting Original Verified Jio STB Captive Lab (Zero-401)
echo ==========================================================
echo [*] Running original initial release scripts from original_repo
echo     - Zero 401 Digest challenges (Direct 200 OK InformResponse)
echo     - 100%% Offline Standalone (No upstream relay dependencies)
echo     - Supports all models: JHSD200, JHSC200, JMSD200, JMSC200
echo ==========================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0original_repo\start-captive-lab.ps1"
pause
