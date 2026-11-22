@echo off
setlocal
cd /d "%~dp0"
set "PATH=%~dp0bin;%PATH%"
call "%~dp0scripts\ensure-python.bat"
if %errorlevel% neq 0 exit /b 1

echo ==========================================================
echo Extracting Jio STB Device Profile and TR-069 Credentials...
echo ==========================================================
python dump_credentials.py
pause
