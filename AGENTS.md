# AI Agent Guidelines & Technical Operational Manual: Jio STB Toolkit

This document defines technical specifications, architectural boundaries, and actionable protocols for autonomous AI agents (Antigravity, Claude Code, Cursor, Gemini CLI) operating or maintaining this repository.

---

## 1. System Architecture

```
+---------------------------------------------------------------------------------+
|                                 STANDALONE MODE                                 |
|                                                                                 |
|  [ PC (query_acs_direct.py) ]  ==== HTTPS:8443 (Digest Auth) ====>  [ Jio ACS ] |
|   - Serial: <STB_SERIAL_NUMBER>                                   (49.40.134.113)
|   - Password: <DERIVED_CPE_PASSWORD>                                            |
+---------------------------------------------------------------------------------+

+---------------------------------------------------------------------------------+
|                                ADB UNLOCK LAB                                   |
|                                                                                 |
|  [ Physical Jio STB ] <==== P2P / Wi-Fi ====> [ captive_lab / mock_acs ]         |
|   - Port 67 (DHCP) -> Assigns IP                                                |
|   - Port 53 (DNS)  -> Spoofs acs.oss.jio.com                                    |
|   - Port 80 (204)  -> Satisfies Android Captive Portal & AES FTTH Netcheck      |
|   - Port 8443(TLS) -> Injects USBDebugging = true & DowngradeEnable = true      |
+---------------------------------------------------------------------------------+

+---------------------------------------------------------------------------------+
|                            FIRMWARE MITM CAPTURE                                |
|                                                                                 |
|  [ Physical Jio STB ] ---- Port 8443 (TLS) ---> [ fota_monitor_acs.py ]          |
|                                                       |                         |
|                                            (Spoofs Firmware Version)            |
|                                                       |                         |
|                                                       +--> [ Real Jio ACS ]     |
|                                                             (49.40.134.113)     |
+---------------------------------------------------------------------------------+
```

---

## 2. Core Operational Protocols for Agents

### Protocol A: Standalone ACS Firmware Query (No Hardware Needed)
When asked to query Jio ACS for updates or test a new version:
1. Do **NOT** require the physical STB to be connected or turned on.
2. If querying for a specific physical STB for the first time, run `python dump_credentials.py` while connected via ADB to save `device_credentials.json`.
3. Execute `query_acs_direct.py` directly on the host machine:
   ```bash
   python query_acs_direct.py <VERSION_STRING>
   ```
4. `query_acs_direct.py` automatically loads `device_credentials.json` if available, or prompts for device details if run standalone without configured credentials.
5. To compute credentials manually for a different serial number $S$ and $ro.acsdata$ $A$, select the vendor's secret key $sk$:
   - SDMC (`JHSD200`): `DahWaethuL9xoo3e`
   - Bluebank (`JHSB200`): `Hee4Xeigaethaeye`
   - Skyworth (`JHSC200`): `Rov5Ifozoobeeth8`
   $$\text{Password} = \text{Base64}\Big(\text{SHA-256}(A + sk)[0:16]\Big).\text{strip}()$$
6. Analyze the SOAP response:
   - Status `200` with `204 No Content`: Device is authenticated; no pending tasks on ACS.
   - Status `200` with `<cwmp:SetParameterValues>`: ACS is configuring device parameters.
   - Status `200` with `<cwmp:Download>`: **FIRMWARE FOUND!** Extract `<URL>`, `<FileSize>`, and `<TargetFileName>`. Automatically saved to `fota_firmware_url.txt` and `fota_update_found.json`.
7. Discovered URLs can be shared to the catalog using `python share_firmware.py` or the Google Form.

---

### Protocol B: Turnkey 1-Click ADB Unlock
1. **Determine Connection Mode:**
   - If PC has Ethernet $\to$ Execute `UNLOCK_ADB_ETHERNET.bat` (or `powershell -File scripts\start-adb-ethernet.ps1`).
   - If PC is Wi-Fi only $\to$ Ensure Windows Mobile Hotspot is ON (2.4 GHz, SSID `JioSTB-Setup`, password `password123`), then execute `UNLOCK_ADB_WIFI.bat`.
2. **Cold Power-Cycle the STB:** Have the user unplug the STB power adapter from the wall, wait 5 seconds, and reconnect.
3. **Monitor Console / Log:**
   - Look for `[INFORM] Device Info:` followed by `InformResponse`.
   - Confirm `*** SUCCESS! STB ACCEPTED Enable USBDebugging (Device.JioSTB)! ADB IS FULLY UNLOCKED! ***`.
   - On SDMC models, SOAP Fault 9005 on `Device.JioSTB.FOTA.Disable` is normal and skipped.
4. **Connect via ADB:**
   ```powershell
   adb connect 192.168.50.2:5555   # (Ethernet)
   adb connect 192.168.137.x:5555  # (Wi-Fi)
   ```
5. **Approve TV Screen Prompt:** Check "Always allow from this computer" on the TV dialog and click OK.

---

### Protocol C: Real-Time Firmware Capture (Ethernet or Wi-Fi MITM)
When capturing live traffic from a physical STB:
1. Ensure `com.iwedia.updateservice` is stopped from flashing payloads:
   ```bash
   adb shell pm disable-user --user 0 com.iwedia.updateservice
   ```
2. Set the target spoofed version in `spoofed_version.txt` (e.g. `STB-JHSD200-11.1.0`).
3. Run `CAPTURE_FIRMWARE_ETHERNET.bat` or `CAPTURE_FIRMWARE_WIFI.bat`.
4. On the STB, navigate to **Settings** $\to$ **System Settings** $\to$ **Software Update**.
5. When `cwmp:Download` is intercepted, verify URL on public Akamai CDN via HTTP Range request.

---

### Protocol D: Automated Post-Unlock Debloating, Hardening & Customization

Once ADB connectivity is established, execute the following autonomous sequence:

#### 1. Hardware & OS Detection
```bash
adb shell getprop ro.product.model       # e.g. JHSD200 or JHSC200
adb shell getprop ro.product.device      # e.g. franklin
adb shell getprop ro.build.version.release # e.g. 11 or 9
```

#### 2. FOTA Neutralization (Model-Specific Branching)
* **For JHS Series (JHSD200 / JHSC200 / JioOS 2.0 / Android 11):**
  Disable the 4 Iwedia OTA services and clear staged blocks:
  ```bash
  adb shell pm disable-user --user 0 com.iwedia.httpupdate
  adb shell pm disable-user --user 0 com.iwedia.updateservice
  adb shell pm disable-user --user 0 com.iwedia.pvodupdateservice
  adb shell pm disable-user --user 0 com.iwedia.updatercuotaservice
  adb shell pm clear com.iwedia.httpupdate
  adb shell pm clear com.iwedia.updateservice
  ```
  > ⚠️ **CRITICAL JHS RULE:** Do **NOT** disable `com.jio.tr069client`! On JHS boxes, `com.jio.tr069client` reads `persist.iwedia.tr.adb.state = 1` and opens `service.adb.tcp.port = 5555` on every cold boot. Disabling it breaks network ADB across reboots.

* **For Legacy JMSC200 / JMSB200 (Android 9):**
  ```bash
  adb shell pm disable-user --user 0 com.jio.httpupdate
  adb shell pm disable-user --user 0 com.jio.usbupdate
  adb shell pm disable-user --user 0 com.jio.tr069client
  adb shell pm disable-user --user 0 insight.tr069.client
  ```

#### 3. Commercial Ads & Telemetry Stripping
Disable startup intro promo ads, telemetry, background trackers, and data collectors:
```bash
adb shell pm uninstall -k --user 0 com.jio.stbadservice
adb shell pm disable-user --user 0 com.jio.bioscopecontentservice
adb shell pm disable-user --user 0 com.jio.screensaver
adb shell pm disable-user --user 0 com.jio.jiobackgroundscheduler
adb shell pm disable-user --user 0 com.jio.appoptimizer
adb shell pm disable-user --user 0 com.jio.userfeedback
adb shell pm disable-user --user 0 com.jio.adc.embedded          # Jio ADC embedded data collector
adb shell pm disable-user --user 0 com.jio.android.jiolauncher  # Jio Patchwall home
```

#### 4. System Visual Enhancement (Permanent Dark Mode)
```bash
adb shell cmd uimode night yes
adb shell settings put secure ui_night_mode 2
```

#### 5. JioStore Management (Debloat or Keep)
* If the user wants a clean, de-Jio'd setup without the bloat of JioStore:
  ```bash
  adb shell pm disable-user --user 0 com.jio.media.stb.jiostore
  adb shell pm disable-user --user 0 com.jio.store
  ```
* Sideload **Aptoide TV** (`apks/AptoideTV.apk`) as a dedicated Android TV app store for remote-friendly TV app downloads without requiring Google Mobile Services (GMS).

#### 6. Clean TV Launcher Sideload & Activation
Sideload Monet Launcher (or Projectivy):
```bash
adb install -r -g apks/monet-launcher.apk
adb shell pm grant com.klevico.monet android.permission.WRITE_SECURE_SETTINGS

# CRITICAL FIX for Jio's PackageManagerService (PMS):
# Jio's PMS has a 'Relax SCAN_REQUIRE_KNOWN' flag and SSO service that automatically
# re-enables disabled apps on cold boot ('pm disable-user' does NOT survive reboot).
# The only persistent fix is 'pm uninstall --user 0', which strips it from user 0's
# active database while keeping the APK intact in /system:
adb shell pm uninstall --user 0 com.iwedia.ui.rjio.launcher.reliance  # JHS / JMSD200A
# (To revert in future: adb shell cmd package install-existing com.iwedia.ui.rjio.launcher.reliance)

# Set Monet as default Home Activity
adb shell cmd package set-home-activity com.klevico.monet/.HomeActivity
adb shell am force-stop com.iwedia.ui.rjio.launcher.reliance
adb shell input keyevent KEYCODE_HOME
```

#### 7. Remote Keymapper (`TVHome.apk`) & Voice Remote Configuration
Sideload the CleanYourTV accessibility button remapper:
```bash
adb install -r -g apks/TVHome.apk

# Grant accessibility service permissions via shell
adb shell settings put secure enabled_accessibility_services com.home.tv/com.home.tv.services.HomeInterceptorService:com.android.talkback/com.google.android.marvin.talkback.TalkBackService
adb shell settings put secure accessibility_enabled 1
```
* **Home Key Interception:** Intercepts the remote's hardcoded "Jio" or "Home" key and redirects directly to your custom launcher.
* **Bluetooth Voice Remote (Mic Button):**
  - Emits `KEYCODE_VOICE_ASSIST` (Linux keycode `231`).
  - Stock handler is `com.android.app.jio.voiceassist`.
  - To remap the Mic button to SmartTube Voice Search, map keycode `231` to `org.smarttube.stable` in `/sdcard/Android/data/com.gathin.tvhome/files/config.json`.
  - To pair/re-pair the Bluetooth Voice Remote: Open Android TV Settings (`am start -n com.android.tv.settings/.MainSettings`), choose **Remotes & Accessories**, and hold **`Back` + `Menu`** for 5 seconds until the remote LED flashes.

#### 8. Google Cast (Chromecast Built-In) Reactivation
The stock cast receiver on Jio Android 11 is broken. Sideload and activate the verified production build:
```bash
adb install -r -d apks/mediashell.apk

# Initialize Google Cast receiver service
adb shell am startservice -a com.google.android.gms.cast.FIRST_SCREEN_JOIN -p com.google.android.apps.mediashell
```
Now native casting from YouTube, Spotify, and Chrome works seamlessly from phones and PCs.

#### 9. Native Android TV Settings Shortcut
```bash
adb install -r -g apks/AndroidSettingsShortcut.apk
```
Enables 1-click access to native Android TV Settings (`com.user.androidsettings`) for Bluetooth audio pairing, Wi-Fi configuration, and Developer Options.

#### 10. Shizuku / Shevery Shell Provider
```bash
adb install -r -g apks/shevery-release.apk
adb shell pm grant com.hamondev.shevery android.permission.WRITE_SECURE_SETTINGS
adb shell pm grant com.hamondev.shevery android.permission.PACKAGE_USAGE_STATS
```

---

## 3. Failure Modes & Automated Recovery

| Failure / Exception | Root Cause | Automated Recovery Action |
| :--- | :--- | :--- |
| **`PermissionDenied` on UDP 53** | Windows DNS Client cache (`Dnscache`) or ICS holds UDP 53. | Execute: `Stop-Service -Name "SharedAccess" -ErrorAction SilentlyContinue`. |
| **`OSError: [WinError 10048]` on 123** | Windows Time Service (`w32time`) owns UDP 123. | Execute: `Stop-Service w32time -Force`. |
| **`FaultCode 9005` (Invalid Parameter)** | STB model does not implement `Device.JioSTB.FOTA.Disable` (e.g. SDMC JHSC200). | Normal schema difference. Ignore fault and proceed; FOTA is frozen via `com.iwedia.*` ADB commands. |
| **Port 8443 TLS Handshake Failure** | STB rejects untrusted certificate chain. | Verify `forged_chain.pem` is loaded. Do not replace with arbitrary self-signed certificates. |
| **ADB Connection Refused (10061)** | Cold boot reset port 5555. | On JHS boxes, verify `com.jio.tr069client` is enabled so it sets port 5555 automatically. Or toggle USB Debugging via `AndroidSettingsShortcut.apk`. |
| **Captive Netcheck Infinite Loop** | STB loops on `/ftth/v1/network/check`. | Respond with `{"Network":"UzLgdFHvJkBfRQiHnNQit+55dub3o1PbxIhuNZ7oJc8="}`. |

---

## 4. Teardown Protocol
When finished, always call:
```cmd
STOP_ALL_LABS.bat
```
This kills all lingering Python processes on ports `53, 67, 80, 123, 443, 7443, 8443, 9443` and restores `w32time`.
