@echo off
title Jio STB Mock ACS Server Console
cd /d "%~dp0.."
call "%~dp0ensure-python.bat"
if %errorlevel% neq 0 exit /b 1

set SCRIPT_NAME=%~1
if "%SCRIPT_NAME%"=="" set SCRIPT_NAME=mock_acs_universal.py

echo ==========================================================
echo Starting Mock ACS Server Console (%SCRIPT_NAME%)...
echo ==========================================================
if "%~2"=="" (
    python "%SCRIPT_NAME%"
) else (
    python %*
)

if %errorlevel% neq 0 (
    echo.
    echo ==========================================================
    echo [ERROR] Mock ACS exited with error code %errorlevel%.
    echo ==========================================================
    pause
)
