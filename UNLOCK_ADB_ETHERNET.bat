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
echo.
echo Select your Jio STB Model Family:
echo   [1] JMS Series: JMSD200A / JMSC200A / AirFiber (JioOS 1.x / SDMC) [DEFAULT]
echo   [2] JHS Series: JHSD200 / JHSC200 / JHSB200 (JioOS 2.0 / Skyworth)
echo.
set MODEL_CHOICE=1
set /p MODEL_CHOICE="Enter choice [1 or 2, default 1]: "
set STB_MODEL=jms
if "%MODEL_CHOICE%"=="2" (
    set STB_MODEL=jhs
    echo [+] Configured for JHS Series (eMudhra chain).
) else (
    echo [+] Configured for JMS Series (RILROOTCA chain).
)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-adb-ethernet.ps1" -AcsScript "mock_acs_universal.py" -Model "%STB_MODEL%"
pause
