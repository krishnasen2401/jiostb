@echo off
rem Jio STB Dependency Check & Auto-Installer

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ================================================================
    echo  [ERROR] Python 3 was not detected on your system!
    echo ================================================================
    echo.
    echo  To use this toolkit, please install Python:
    echo    1. Download from: https://www.python.org/downloads/
    echo    2. Run installer and CHECK: "Add Python to PATH"
    echo    3. Restart your terminal or computer, then run this again.
    echo.
    echo ================================================================
    echo.
    pause
    exit /b 1
)

rem Ensure required packages (pycryptodome, requests, urllib3) are installed
python -c "from Crypto.Cipher import AES; import requests, urllib3, sys" >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Installing required Python packages from requirements.txt...
    python -m pip install -q -r "%~dp0..\requirements.txt" --disable-pip-version-check
    if %errorlevel% neq 0 (
        python -m pip install -q -r "%~dp0..\requirements.txt" --user --disable-pip-version-check
    )
    python -c "from Crypto.Cipher import AES; import requests, urllib3, sys" >nul 2>&1
    if %errorlevel% neq 0 (
        echo [!] Bootstrapping pip and retrying...
        python -m ensurepip --default-pip >nul 2>&1
        python -m pip install -r "%~dp0..\requirements.txt" --disable-pip-version-check
    )
)

exit /b 0
