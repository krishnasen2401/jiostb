@echo off
setlocal enabledelayedexpansion
title Jio STB - Voice & JioStore Diagnostics Collector
color 0B

echo =====================================================================
echo          JIO STB VOICE & JIOSTORE DIAGNOSTICS COLLECTOR
echo =====================================================================
echo.

:: 1. Locate ADB binary
set "ADB=adb"
if exist "%~dp0bin\adb.exe" (
    set "ADB=%~dp0bin\adb.exe"
) else if exist "C:\Users\krishnasen\Desktop\jiostbdocs\jio-fota-toolkit\bin\adb.exe" (
    set "ADB=C:\Users\krishnasen\Desktop\jiostbdocs\jio-fota-toolkit\bin\adb.exe"
)

:: 2. Check for connected devices
echo [*] Checking connected ADB devices...
"%ADB%" devices

echo.
echo [*] IMPORTANT: Ensure your Android phone is disconnected or not interfering.
echo     If your STB is not listed above, enter its IP address below.
set /p STB_IP="Enter STB IP address (or press Enter if already connected): "

if not "%STB_IP%"=="" (
    echo [*] Connecting to %STB_IP%:5555...
    "%ADB%" connect %STB_IP%:5555
    set "DEVICE_TARGET=-s %STB_IP%:5555"
) else (
    set "DEVICE_TARGET="
)

set "OUTFILE=%USERPROFILE%\Desktop\stb_voice_and_jiostore_report.txt"

echo.
echo [*] Running full diagnostic scan on STB...
echo [*] Saving output to: %OUTFILE%

(
echo =====================================================================
echo            JIO STB DIAGNOSTIC REPORT: VOICE & JIOSTORE
echo            Generated: %DATE% %TIME%
echo =====================================================================
echo.

echo ---------------------------------------------------------------------
echo [DEVICE INFORMATION]
echo ---------------------------------------------------------------------
"%ADB%" %DEVICE_TARGET% shell getprop ro.product.model
"%ADB%" %DEVICE_TARGET% shell getprop ro.product.manufacturer
"%ADB%" %DEVICE_TARGET% shell getprop ro.build.display.id
"%ADB%" %DEVICE_TARGET% shell getprop ro.serialno
echo.

echo ---------------------------------------------------------------------
echo [PART 1: VOICE RECOGNITION DIAGNOSTICS]
echo ---------------------------------------------------------------------
echo.
echo === 1.1 INSTALLED VOICE / SPEECH PACKAGES ===
"%ADB%" %DEVICE_TARGET% shell pm list packages | findstr /i "voice speech google recognizer assistant jio"
echo.

echo === 1.2 ENABLED VOICE / SPEECH PACKAGES ===
"%ADB%" %DEVICE_TARGET% shell pm list packages -e | findstr /i "voice speech google recognizer assistant jio"
echo.

echo === 1.3 ALL CURRENTLY DISABLED / FROZEN PACKAGES ===
"%ADB%" %DEVICE_TARGET% shell pm list packages -d
echo.

echo === 1.4 SYSTEM VOICE SETTINGS ===
echo voice_interaction_service:
"%ADB%" %DEVICE_TARGET% shell settings get secure voice_interaction_service
echo voice_recognition_service:
"%ADB%" %DEVICE_TARGET% shell settings get secure voice_recognition_service
echo.

echo === 1.5 JIO VOICE ASSISTANT PERMISSION & DUMPSYS ===
echo Checking RECORD_AUDIO permission:
"%ADB%" %DEVICE_TARGET% shell dumpsys package com.android.app.jio.voiceassist | findstr /i "android.permission.RECORD_AUDIO"
echo.

echo === 1.6 CLEANYOURTV / TVHOME HOTKEY CONFIGURATION ===
echo Checking /sdcard/Android/data/com.gathin.tvhome/files/config.json:
"%ADB%" %DEVICE_TARGET% shell cat /sdcard/Android/data/com.gathin.tvhome/files/config.json
echo.

echo ---------------------------------------------------------------------
echo [PART 2: JIOSTORE & OTT SUBSCRIPTION DIAGNOSTICS]
echo ---------------------------------------------------------------------
echo.
echo === 2.1 JIOSTORE PACKAGE STATE ===
echo Check if com.jio.store is installed:
"%ADB%" %DEVICE_TARGET% shell pm list packages com.jio.store
echo Check if com.jio.store is enabled:
"%ADB%" %DEVICE_TARGET% shell pm list packages -e com.jio.store
echo Check if com.jio.store is disabled:
"%ADB%" %DEVICE_TARGET% shell pm list packages -d com.jio.store
echo.

echo === 2.2 JIOSTORE PROCESS & SERVICE STATUS ===
"%ADB%" %DEVICE_TARGET% shell ps | findstr /i "jio.store"
echo.

echo === 2.3 JIO SSO & ACCOUNT SERVICES (REQUIRED FOR OTT / JIOTV+) ===
echo SSO Service (com.media.jio.sso.stb):
"%ADB%" %DEVICE_TARGET% shell pm list packages -e com.media.jio.sso.stb
echo Account Service (com.jio.media.stb.account):
"%ADB%" %DEVICE_TARGET% shell pm list packages -e com.jio.media.stb.account
echo Universal Setup (com.jio.universalsetup):
"%ADB%" %DEVICE_TARGET% shell pm list packages -e com.jio.universalsetup
echo TR-069 Client (com.jio.tr069client):
"%ADB%" %DEVICE_TARGET% shell pm list packages -e com.jio.tr069client
echo.

echo === 2.4 INSTALLED OTT STREAMING PACKAGES ===
echo Disney+ Hotstar (in.startv.hotstar):
"%ADB%" %DEVICE_TARGET% shell pm list packages in.startv.hotstar
echo SonyLIV (com.sonyliv):
"%ADB%" %DEVICE_TARGET% shell pm list packages com.sonyliv
echo Zee5 (com.graymatrix.did):
"%ADB%" %DEVICE_TARGET% shell pm list packages com.graymatrix.did
echo JioCinema (com.jio.media.ondemand):
"%ADB%" %DEVICE_TARGET% shell pm list packages com.jio.media.ondemand
echo JioTV+ (com.jio.media.jiotvplus):
"%ADB%" %DEVICE_TARGET% shell pm list packages com.jio.media.jiotvplus
echo SunNXT (com.suntv.sunnxt):
"%ADB%" %DEVICE_TARGET% shell pm list packages com.suntv.sunnxt
echo.

echo =====================================================================
echo                          END OF REPORT
echo =====================================================================
) > "%OUTFILE%" 2>&1

echo.
echo [!] Scan complete!
echo [+] Report saved to: %OUTFILE%
echo [*] Opening report in Notepad...
start notepad "%OUTFILE%"

echo.
pause
