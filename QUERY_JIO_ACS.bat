@echo off
setlocal
cd /d "%~dp0"
call "%~dp0scripts\ensure-python.bat"
if %errorlevel% neq 0 exit /b 1

echo ==========================================================
echo       QUERY JIO TR-069 ACS DIRECTLY (RESEARCH TOOL)
echo ==========================================================
echo.
echo [!] NOTE: This script is for advanced research / firmware checking ONLY.
echo     You do NOT need this script to unlock ADB on your STB!
echo     To unlock ADB on your Jio STB, run: UNLOCK_ADB_ETHERNET.bat
echo.
echo [!] REQUIREMENT: Requires an active JioFiber internet connection
echo     to reach Jio's upstream ACS server (49.40.134.113:8443).
echo.

set /p SVER="Enter Software Version to spoof [Default: STB-JHSD200-11.1.0]: "
if "%SVER%"=="" set SVER=STB-JHSD200-11.1.0

echo.
echo Running query with version: %SVER%
python query_acs_direct.py "%SVER%"

echo.
pause
