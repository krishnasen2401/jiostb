@echo off
setlocal
cd /d "%~dp0"
call "%~dp0scripts\ensure-python.bat"
if %errorlevel% neq 0 exit /b 1

echo ==========================================================
echo       JIO STB FOTA LAB - WI-FI HOTSPOT MODE (1-CLICK)
echo ==========================================================
echo.

net session >nul 2>&1
if %errorLevel% == 0 (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-wifi-lab.ps1"
) else (
    echo [i] Requesting Administrator Privileges...
    powershell.exe -NoProfile -Command "Start-Process cmd.exe -ArgumentList '/k \"\"%~f0\"\"' -Verb RunAs"
)
