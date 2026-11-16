# Reliance Jio STB Complete Debloating, Lockdown & Customization Guide

This guide details how to permanently lock down the Reliance Jio STB (JHS D200 v2 / JHS C200 / franklin) once ADB is enabled. It eliminates all Jio ads, telemetry, and background updaters while setting up a clean Android TV launcher (Projectivy), native Android TV Settings, and custom remote hotkeys.

---

## 1. Automated 1-Click Post-ADB Setup (Recommended)

To automate the entire debloating, launcher installation, hotkey remapping, and dark mode configuration in a single click:
1. Double-click **[`1CLICK_POST_ADB_SETUP.bat`](1CLICK_POST_ADB_SETUP.bat)** (or run `python post_adb_setup.py`).
2. The interactive script will automatically:
   - Verify connection and detect your STB model (`JHSD200`, `JHSC200`, `JHSB200`).
   - Freeze all Iwedia OTA update services while protecting `com.jio.tr069client` (ensuring ADB stays persistent).
   - Disable Jio ads, bioscope, telemetry, and background trackers.
   - Install all bundled utility APKs (`Monet Launcher`, `OpenShelf FOSS App Store`, `Shevery`, `Google Cast mediashell`, `Aurora Store`, `Settings shortcuts`, `TVHome`).
   - Bypass the Jio PMS `Relax SCAN_REQUIRE_KNOWN` reboot bug by cleanly uninstalling the stock launcher for user `0` and activating Monet as default home.
   - Configure CleanYourTV hotkeys (Netflix $\to$ Monet, Hotstar $\to$ Aurora Store, Prime $\to$ Android Settings).
   - Enforce permanent Android TV Dark Mode.
   - Dump your device's TR-069 credentials profile (`device_credentials.json`).

---

## 2. Manual Step-by-Step Debloat Commands

If you prefer executing the shell commands manually via ADB (`adb connect <STB_IP>:5555`), follow the sections below:

### A. Disable All OTA Updaters & TR-069 Daemons

> [!WARNING]
> **Important Note for JHS Series (JHSC200 / JHSD200 / JioOS 2.0):**  
> Do **NOT** disable or uninstall `com.jio.tr069client` on JHS boxes!  
> On JHS boxes, `com.jio.tr069client` reads `persist.iwedia.tr.adb.state` at each boot and activates network ADB (`service.adb.tcp.port = 5555`). Disabling it will cause ADB to drop offline after reboot. Keep `com.jio.tr069client` enabled and only disable the Iwedia OTA services (`com.iwedia.*`).

```bash
# Iwedia OTA update services (Disable on all JHS boxes to block OTAs)
pm disable-user --user 0 com.iwedia.updateservice
pm disable-user --user 0 com.iwedia.httpupdate
pm disable-user --user 0 com.iwedia.pvodupdateservice
pm disable-user --user 0 com.iwedia.updatercuotaservice
pm clear com.iwedia.httpupdate
pm clear com.iwedia.updateservice

# For JMSC200 / JMSB200 (Legacy JioOS) only:
# pm disable-user --user 0 com.jio.tr069client
# pm disable-user --user 0 insight.tr069.client
```

### B. Disable Jio Ads, Telemetry & Diagnostics
```bash
# Ads & Content Injection
pm disable-user --user 0 com.jio.stbadservice
pm disable-user --user 0 com.jio.bioscopecontentservice
pm disable-user --user 0 com.jio.screensaver

# Telemetry & Background Schedulers
pm disable-user --user 0 com.jio.jiobackgroundscheduler
pm disable-user --user 0 com.jio.appoptimizer
pm disable-user --user 0 com.jio.adc.embedded
pm disable-user --user 0 com.jio.adc.aka
pm disable-user --user 0 com.jio.systemstats
pm disable-user --user 0 com.rjil.jiostblogservice
pm disable-user --user 0 com.jio.stb.remotediagnose
# Optional: com.jio.store is intentionally preserved!
# Jio STB lacks Google Play Services (GMS). JioStore provides official
# AOSP-tailored versions of Zee5, SonyLIV, etc. that do not crash.
# pm disable-user --user 0 com.jio.store
pm disable-user --user 0 com.jio.universalsetup
pm disable-user --user 0 com.netflix.partnertoken

# Optional: Jio Voice Assistant (Only disable if remapping Mic button or using Google Assistant)
# pm disable-user --user 0 com.android.app.jio.voiceassist
```

### C. Install & Configure Custom Launcher (Projectivy or Monet)

Both **Projectivy Launcher** and **Monet Launcher** are included prebuilt in [`apks/`](apks/):

1. **Option 1: Projectivy Launcher (Recommended)**
   - Premium Leanback smart TV UI with custom category rows, "Watch Next" channels, custom wallpapers, and input switching.
   ```bash
   adb install -r apks/ProjectivyLauncher.apk
   adb shell cmd package set-home-activity com.spocky.projengmenu/.ui.home.MainActivity
   adb shell pm grant com.spocky.projengmenu android.permission.WRITE_SECURE_SETTINGS
   adb shell appops set com.spocky.projengmenu SYSTEM_ALERT_WINDOW allow
   adb shell settings put secure enabled_accessibility_services com.spocky.projengmenu/.services.ProjectivyAccessibilityService
   adb shell settings put secure accessibility_enabled 1
   adb shell am start -n com.spocky.projengmenu/.ui.home.MainActivity
   ```

2. **Option 2: Monet Launcher**
   - Ultra-lightweight minimalist Material You grid launcher (~30–40 MB RAM).
   ```bash
   adb install -r apks/monet-launcher.apk
   adb shell cmd package set-home-activity com.klevico.monet/.HomeActivity
   adb shell pm grant com.klevico.monet android.permission.WRITE_SECURE_SETTINGS
   adb shell settings put secure enabled_accessibility_services com.klevico.monet/.LauncherAccessibilityService
   adb shell settings put secure accessibility_enabled 1
   adb shell am start -n com.klevico.monet/.HomeActivity
   ```

> [!CRITICAL]
> **Persistent Launcher Fix (Jio PackageManagerService Quirk):**  
> On Jio STB firmware, `pm disable-user --user 0 com.iwedia.ui.rjio.launcher.reliance` **does NOT survive a cold reboot!**  
> Jio's customized `PackageManagerService` contains a flag named `Relax SCAN_REQUIRE_KNOWN` and an SSO service that automatically re-enables disabled apps on boot.  
>  
> To permanently remove the iWedia launcher across cold reboots:
> ```bash
> pm uninstall --user 0 com.iwedia.ui.rjio.launcher.reliance
> ```
> This removes the launcher registration for user 0 while leaving the APK safely in the read-only `/system` partition. Jio's bootloader does NOT reinstall uninstalled user packages.  
> *(To restore it anytime: `cmd package install-existing com.iwedia.ui.rjio.launcher.reliance`)*

Kill the stock launcher process:
```bash
am force-stop com.iwedia.ui.rjio.launcher.reliance
```

### D. System Visual Enhancement (Permanent Dark Mode)
Force true dark mode across all Android TV system menus and settings:
```bash
cmd uimode night yes
settings put secure ui_night_mode 2
```

---

## 2. On-Device Shell & App Management (No PC Needed Afterward)

### A. Shevery (`apks/shevery-release.apk`) — On-Device Shizuku Shell
* **What it is:** **Shevery** (`com.hamondev.shevery`) is a standalone, on-device **Shizuku API provider**.
* **Why use it:** Once ADB is unlocked, installing Shevery gives you persistent `uid=2000(shell)` privileges directly on the TV. You can install APKs silently, freeze/unfreeze apps, and grant runtime permissions directly from the TV without plugging in a PC!
* **Installation:**
  ```bash
  adb install apks/shevery-release.apk
  ```

### B. OpenShelf (`apks/OpenShelf-0.7.0.apk`) — FOSS Android TV App Store
* **What it is:** An open-source TV app store by [wingedpanther/openshelf](https://github.com/wingedpanther/openshelf) that indexes over 3,000+ open-source Android TV applications directly from their GitHub releases.
* **Why use it:** Discover and install apps like SmartTube, Kodi, Stremio, NewPipe, and open-source launchers directly using only the TV remote control! It automatically picks the matching CPU architecture (`armeabi-v7a` or `arm64-v8a`), checks signing keys, and updates itself.
* **Installation:**
  ```bash
  adb install apks/OpenShelf-0.7.0.apk
  adb shell appops set io.github.wingedpanther.openshelf REQUEST_INSTALL_PACKAGES allow
  ```

### C. Aurora Store (`apks/AuroraStore_4.8.4.apk`) — Open-Source Play Store
* **What it is:** An open-source, privacy-friendly Google Play Store client for Android TV.
* **Why use it:** Allows downloading, installing, and updating any Android TV application without Google Play Services or logging into a personal Google account.
* **Installation:**
  ```bash
  adb install apks/AuroraStore_4.8.4.apk
  ```

---

## 3. Upgrading the Google Cast (Chromecast Built-In) Stub

### The Problem: Hollow Stub
On stock Jio firmware, casting from YouTube, Chrome, or smartphones fails. Inspection of the system partition reveals:
* Jio ships `com.google.android.apps.mediashell` as an empty **0 MB stub** (`v0.0`, versionCode `1`) in `/product/priv-app/AndroidMediaShell`.
* Because it is only a placeholder stub, the Chromecast receiver service does not run.

### The Fix: Official Production Update (`apks/mediashell.apk`)
We captured the genuine production Google Cast receiver update (`v3.72.446070`, versionCode `446070112`) and bundled it in [`apks/mediashell.apk`](apks/mediashell.apk):

1. **Install the Production Cast Receiver:**
   ```bash
   adb install -r apks/mediashell.apk
   ```
2. **Verify Cast Service Activation:**
   ```bash
   adb shell dumpsys activity services com.google.android.apps.mediashell
   ```
   * The STB registers `CastReceiverService` with Google Cast client ID.
   * Your TV immediately begins broadcasting as a genuine **Chromecast built-in** receiver (e.g. "Living Room TV") across your local Wi-Fi network!
3. **DIAL Protocol Casting & YouTube Handling:**
   * **Keep `com.jio.dialserver` enabled:** It provides the **DIAL (Discovery And Launch)** protocol created by Netflix and YouTube, allowing phone apps to discover the TV on the local network.
   * **How YouTube Casting Works on Jio STB:**
     * Reliance's factory DIAL server specifically maps YouTube cast requests from phones to carrier-branded `com.jio.yt` (an embedded Chromium WebView wrapper).
     * **If `com.jio.yt` is enabled:** The phone casts to Jio's WebView player. It works for basic playback, but runs with unskippable ads, clunky navigation, and poor 4K/HDR performance.
     * **Recommended (SmartTube):** Sideload SmartTube (`org.smarttube.stable`). SmartTube includes its own built-in DIAL receiver and permanent "Link with TV Code" (`youtube.com/pair`). Once linked, phones cast directly to SmartTube with zero ads, SponsorBlock, and full 4K 60fps HDR.
     * **Official YouTube TV APK (`com.google.android.youtube.tv`):** Can be installed via Aurora Store, but Google account sign-in and voice search require microG due to uncertified AOSP status.

---

## 4. Important Notice: JioTV+ & Jio SSO (`com.media.jio.sso.stb`)

> [!WARNING]
> **DO NOT DISABLE `com.media.jio.sso.stb` if you plan to use JioTV+ or LiveTV!**

* **Why:** All Jio media apps (`com.jio.media.jiotvplus`, `com.jio.media.livetv`, `com.jio.myjiotv`) rely on Jio's Single Sign-On service via intent `app://open.sso.app`.
* If `com.media.jio.sso.stb` is uninstalled or disabled, launching JioTV+ triggers a fatal `ActivityNotFoundException` crash.
* **If you accidentally disabled it, restore it via:**
  ```bash
  cmd package install-existing com.media.jio.sso.stb
  pm enable com.media.jio.sso.stb
  ```

## 5. Restoring Native Android TV Settings vs. Jio Settings

On stock Jio firmware, Jio hardcodes their proprietary settings app (`com.rjil.jiostbsetting`) with an intent filter `priority="999"` for `android.settings.SETTINGS`. This forcefully hijacks all settings clicks and hides standard Android TV options (such as developer options, accessibility services, app permissions, and storage).

When `com.rjil.jiostbsetting` is disabled, the standard "Settings" icon may fail to open in custom launchers.

### The Solution: Bundled Settings Shortcut APKs
Inside [`apks/`](apks/), we provide two dedicated lightweight launcher shortcuts:

1. **`AndroidSettingsShortcut.apk` (`com.user.androidsettings`)**:
   - Opens the genuine, native **Android TV Settings** (`com.android.tv.settings/.MainSettings`).
   - Gives direct access to: Apps, Permissions, Display & Sound, Developer Options, Accessibility, and Account Management.
   - Install via ADB:
     ```bash
     adb install apks/AndroidSettingsShortcut.apk
     ```
   - Manual ADB launch command:
     ```bash
     adb shell am start -n com.android.tv.settings/.MainSettings
     ```

2. **`JioSettingsShortcut.apk` (`com.user.jiosettings`)**:
   - Opens **Jio Settings** (`com.rjil.jiostbsetting/.MainActivity`) as a standalone app without letting it hijack system-wide settings.
   - Useful if you need to pair Bluetooth remotes, scan DVB-C cable channels, or check Jio subscription diagnostics.
   - Install via ADB:
     ```bash
     adb install apks/JioSettingsShortcut.apk
     ```

---

## 6. Remote Control Key Remapping (CleanYourTV)

Jio remotes feature dedicated shortcut buttons that normally force-launch Jio apps or stay dead when stock apps are uninstalled.

Using **CleanYourTV** ([`apks/TVHome.apk`](apks/TVHome.apk)), these keys can be routed to your preferred media apps:

### Key Event Mapping Reference
| Button Name | Linux Keycode | Android Keycode Constant | Recommended Target Application | Target Package Name |
| :--- | :---: | :--- | :--- | :--- |
| **Netflix** | `137` | `KEYCODE_F7` | Netflix | `com.netflix.ninja` |
| **Disney+ Hotstar** | `138` | `KEYCODE_F8` | Disney+ Hotstar | `in.startv.hotstar` |
| **JioCinema** | `139` | `KEYCODE_F9` | JioCinema | `com.jio.media.ondemand` |
| **Custom / Apps** | `140` | `KEYCODE_F10` | SmartTube | `org.smarttube.stable` |
| **JioTV+ / Guide** | `131`, `136`, `170`, `172` | `KEYCODE_TV`, `KEYCODE_GUIDE` | JioTV+ (Live TV) | `com.jio.media.jiotvplus` |
| **Mic / Voice** | `231` | `KEYCODE_VOICE_ASSIST` | Jio Voice Assistant | `com.android.app.jio.voiceassist` |

### Configuration File Setup
CleanYourTV stores key bindings in `/sdcard/Android/data/com.gathin.tvhome/files/config.json`:
```json
{
  "keyMappings": [
    {"keyCode": 137, "action": "launch_app", "packageName": "com.netflix.ninja"},
    {"keyCode": 138, "action": "launch_app", "packageName": "in.startv.hotstar"},
    {"keyCode": 139, "action": "launch_app", "packageName": "com.jio.media.ondemand"},
    {"keyCode": 140, "action": "launch_app", "packageName": "org.smarttube.stable"},
    {"keyCode": 131, "action": "launch_app", "packageName": "com.jio.media.jiotvplus"},
    {"keyCode": 231, "action": "launch_app", "packageName": "org.smarttube.stable"}
  ]
}
```
Ensure the Accessibility Service is enabled:
```bash
settings put secure enabled_accessibility_services com.gathin.tvhome/.InputKeyService
```

### Alternative: Key Mapper (`apks/KeyMapper.apk`)
For advanced visual button remapping (short press, double tap, long press combinations):
1. Install Key Mapper:
   ```bash
   adb install -r apks/KeyMapper.apk
   pm grant io.github.sds100.keymapper android.permission.WRITE_SECURE_SETTINGS
   settings put secure enabled_accessibility_services io.github.sds100.keymapper/.system.accessibility.MyAccessibilityService
   ```
2. Open Key Mapper on your TV to record triggers and assign custom actions, app launches, or key events.

---

### Voice Remote (Mic Button) & Bluetooth Remote Configuration

The official Jio remote communicates via Bluetooth Low Energy (BLE HID) and includes an onboard microphone for voice commands.

#### 1. Why Third-Party Voice Typing (SmartTube / Assistant) Fails on Jio Remote
Through low-level AudioFlinger, DEX decompilation, and Bluetooth GATT reverse-engineering on live hardware:
* **Hardcoded Package Whitelist in `RecognitionService`:** DEX disassembly of `com.android.app.jio.voiceassist` (`VoiceServiceWrapper`, method 34264) reveals an explicit check on `calling_package`. When any third-party app (such as SmartTube `org.smarttube.stable` or Google Assistant) attempts to invoke the Android `RecognitionService`, Jio logs:
  ```
  No allowed app found. Access of Recognition service denied.
  recogError==>true
  ```
* **No Android Audio HAL Bridge:** When third-party apps attempt to record audio directly via `android.media.AudioRecord`, Android's AudioFlinger reports:
  ```
  Input device: 0 (AUDIO_DEVICE_NONE)
  ```
  There is zero ALSA audio driver bridge between the remote and the Linux kernel.
* **Proprietary BLE GATT Voice Stream & Handshake:**
  The remote does not stream raw PCM over standard Bluetooth audio profiles. Instead, audio is negotiated over proprietary Bluetooth Low Energy GATT characteristics:
  - **GATT Service UUID:** `8980f798-0614-11ea-8d71-362b9e155667`
  - **Audio Data Characteristic:** `8980f9fa-0614-11ea-8d71-362b9e155667`
  - **Audio Control Characteristic:** `8980f9fb-0614-11ea-8d71-362b9e155667`
* **Why the Remote LED Blinks Constantly:**
  In `voiceassist.apk` (`ServiceBleVoiceRead`), starting audio requires an active GATT handshake (`open mic` $\to$ `GATT_VOICE_AUDIO_START`). If the STB fails to write to the control characteristic (`writeCharacteristic error` / `gattService null`), the remote's LED blinks continuously waiting for confirmation. After 5 seconds of receiving zero audio packets, the STB times out with `"intent": "error: empty input"`.

#### 2. Workarounds for Full Voice Typing in SmartTube & Google Assistant
1. **Push-to-Talk with Jio Voice:** Press and **hold** the Mic button continuously while speaking near the top of the remote.
2. **USB Air Mouse / Mic Remote (Universal Solution):**  
   Plugging any standard 2.4GHz USB wireless air mouse (such as a G10s / G20s with USB dongle) provides a standard USB Audio Class input device (`/dev/snd/pcmC1D0c`). SmartTube, Google Assistant, and Kodi can record from it natively without any proprietary restrictions!
3. **Smartphone Remote (Google TV / JioHome):**  
   Using the virtual remote in the Google TV or JioHome smartphone app streams voice input from your phone's microphone directly into Android TV search fields over Wi-Fi.

#### 3. Bluetooth Voice Remote Pairing & Troubleshooting
If the remote disconnects or you need to re-pair it:
1. Open native Android TV Settings via our shortcut:
   ```bash
   adb shell am start -n com.android.tv.settings/.MainSettings
   ```
2. Navigate to **Remotes & Accessories** $\to$ **Add Accessory**.
3. On the Jio Voice Remote, press and hold the **`Back` + `Menu`** buttons simultaneously for 5 seconds until the blue/red status LED blinks rapidly.
4. Select **JioRemote** on the TV screen to complete Bluetooth pairing. Microphones, volume keys, and custom hotkeys will resume working immediately.
```bash
settings put secure enabled_accessibility_services com.gathin.tvhome/.InputKeyService
```

---

## 7. Low-Level Network Discoveries & System Mechanics

### A. NTP Time Synchronization (UDP Port 123)
* **The Mechanism:** Upon boot, TeleOS verifies real-world time before attempting any TLS handshake with Jio ACS or Google servers.
* **The Bottleneck:** Windows Host runs the Windows Time Service (`w32time`), which binds exclusively to UDP port 123.
* **Our Fix:** The lab launcher scripts automatically stop `w32time` (`Stop-Service w32time -Force`) so Python's high-precision RFC 5905 NTP server can answer the STB with 64-bit real-world timestamps.

### B. Private DNS / DoT (TCP Port 853) Dropping
* **The Mechanism:** On Android 11, the operating system attempts to establish encrypted DNS connections (DNS-over-TLS) to Google or Cloudflare DNS servers on TCP port 853. If successful, this bypasses local DNS spoofing on port 53.
* **Our Fix:** The captive lab (`captive_lab.py`) opens TCP port 853 and immediately terminates or drops connections, forcing Android TV to fall back to unencrypted local DNS queries on UDP port 53.

### C. Captive Portal Detection (HTTP Port 80)
* **The Mechanism:** Android TV sends `GET http://connectivitycheck.gstatic.com/generate_204` on TCP port 80. If it receives a redirect, timeout, or non-204 status, it marks the network connection as `NO_INTERNET` and disables background cloud services.
* **Our Fix:** The captive responder listens on port 80 and returns an immediate `HTTP/1.1 204 No Content` reply with zero body, clearing the Android network validation check instantly.

---

## 8. Firmware Downgrading Mechanics (`DowngradeEnable`)

Jio STBs normally block flashing older firmware using anti-rollback timestamp checks. However, Jio engineers embedded a TR-181 override parameter:
* **`Device.JioSTB.FOTA.DowngradeEnable`** (`true`)
* **`Device.JioSTB.FOTA.DowngradeValidityDate`** (`2037-12-31T23:59:59.000Z`)

### How it Works:
1. When `DowngradeEnable = true` is injected via our mock ACS (`mock_acs_universal.py`), the internal FOTA service (`com.iwedia.updateservice`) disables the version timestamp check:
   $$\text{AllowUpdate} = (\text{TargetVersion} > \text{CurrentVersion}) \lor (\text{DowngradeEnable} == \text{true})$$
2. The STB can then accept an older full block OTA package (e.g. downgrading from `11.3.46` to `11.1.0` or `11.3.24`) provided via our local captive responder.

---

## 9. Reversing / Restoring Stock State

Because all debloating is performed under `--user 0`, the modifications are **100% reversible**:
* **To re-enable any specific app:**
  ```bash
  pm enable <package_name>
  ```
* **To restore an uninstalled system app:**
  ```bash
  cmd package install-existing <package_name>
  ```
* **Full Factory Reset:**
  Settings $\to$ Device Preferences $\to$ Reset, or booting into Recovery (`adb reboot recovery`) restores the box to untouched factory defaults.

---

## 10. JioTV+ v6 Upgrade Guide (Modern Android TV UI & Any-ISP Mobile Login)

### Why Upgrade to JioTV+ v6?
* **Factory Stock STB (v2.6.7):** Ships with a 3-year-old clunky interface tied strictly to the iWedia launcher and requires an active JioFiber connection bound to the box's MAC address via `com.media.jio.sso.stb`.
* **Play Store Android TV Build (v6.0.10):** Features a modern Android TV Leanback UI, fast channel guide (EPG), lower player latency, and standalone authentication.

### Does it Work with a Normal Jio Mobile Number?
**YES!** Unlike the factory v2.x build which is locked to your STB's hardware and JioFiber connection:
* **JioTV+ v6 has a standalone OTP login screen.**
* You can log in using **ANY active Jio mobile number** (prepaid or postpaid) or JioFiber RMN that has a JioTV+ plan entitlement.
* You receive an SMS OTP on your phone, enter it on the TV screen, and all 800+ live TV channels and on-demand content play flawlessly over **ANY network or ISP** (Airtel, ACT, BSNL, local fiber, mobile hotspot, or Ethernet)!

### Installation via ADB Split APKs:
Jio STBs run 32-bit ARM (`armeabi-v7a`). Obtain the official `JioTV+ 6.0.10` APKS bundle, extract it, and install all splits simultaneously using `install-multiple`:

```bash
adb install-multiple -r base.apk split_config.armeabi_v7a.apk split_config.xhdpi.apk split_config.en.apk
```

To launch JioTV+ v6:
```bash
adb shell am start -n "com.jio.media.jiotvplus/com.jio.jioplay.jiotvplustwo.MainActivity"
```

---

## 11. Verified Hardware Profile: JMSD200A (Jio AirFiber Android 11 / Build 25.1.9)

The **JMSD200A** (bundled with Jio AirFiber installations) has been fully tested and validated:

### 1. ADB Unlock Specifics
* **Hardware Family:** Select **Option 1 (JMS Series)** in `UNLOCK_ADB_ETHERNET.bat`.
* **Certificate Pinning:** Uses `acs_chain.pem` (RILROOTCA root certificate).
* **TR-069 Service:** Connects on port `8443` or `9443` ~45–60 seconds after power-on.
* **Result:** ADB port `5555` becomes active immediately.

### 2. Confirmed Working Debloat Target Packages
The following ad and update services can be safely disabled without breaking persistent ADB:
```bash
# Firmware Updaters
pm disable-user --user 0 com.jio.httpupdate
pm disable-user --user 0 com.jio.usbupdate

# Ads, Screen Savers & Telemetry
pm disable-user --user 0 com.jio.stbadservice
pm disable-user --user 0 com.jio.bioscopecontentservice
pm disable-user --user 0 com.jio.screensaver
pm disable-user --user 0 com.jio.adc.embedded
pm disable-user --user 0 com.jio.adc.aka
pm disable-user --user 0 com.jio.appoptimizer
pm disable-user --user 0 com.jio.backgroundscheduler
pm disable-user --user 0 com.jio.systemstats
pm disable-user --user 0 com.jio.stb.remotediagnose
pm disable-user --user 0 com.jio.universalsetup
```

### 3. Launcher Selection: Projectivy vs. Monet on JMSD200A
* **Projectivy Launcher (v4.73):** **Recommended for daily TV use.** Provides standard 10-ft Android TV UI, "Watch Next" rows, integrated channel categories (NuvioTV, SmartTube, Kodi), and runs at solid 60fps on JMSD200A's quad-core Amlogic SoC with `0.5x` animation scales.
* **Monet Launcher:** Best for ultra-minimalist setups. Uses only ~30–40 MB RAM with clean Material You app grid.

### 4. Remote Key Mapping with CleanYourTV / KeyMapper
* **Netflix (KeyCode 137):** Projectivy / Monet Home
* **Hotstar (KeyCode 138):** Aurora Store / SmartTube
* **Prime Video (KeyCode 134):** Native Android TV Settings (`com.android.tv.settings`)
* **JioTV+ (KeyCode 141):** NuvioTV (`com.nuvio.tv`)
* **Extra / Apps (KeyCode 142):** Shevery local root shell

---

## 12. Resolving Zee5, SonyLIV & OTT App Crashes: Non-GMS AOSP vs. JioStore

### The Root Cause: Why Generic TV APKs Crash
* Reliance Jio STBs run non-GMS AOSP Android (without certified Google Play Services or `com.google.android.gms`).
* Generic TV APKs downloaded from APKMirror, APKPure, or Aurora Store (such as **Zee5**, **SonyLIV**, **SunNXT**, and **Hotstar**) compile against Google Play Services for authentication and analytics.
* When launched on a Jio STB, these apps throw:
  ```text
  java.lang.NoClassDefFoundError: Failed resolution of: Lcom/google/android/gms/common/GoogleApiAvailability;
  ```
  and instantly crash back to the home screen.

### Solution 1: Keep JioStore Enabled (Recommended)
Reliance Jio partners with OTT providers to distribute custom, AOSP-tailored versions of these apps specifically built for Jio STB hardware with all GMS dependencies stripped out.
* In our latest toolkit update, `com.jio.store` is **preserved by default** and excluded from debloating.
* If you previously disabled JioStore, re-enable and open it using:
  ```bash
  adb shell pm enable com.jio.store
  adb shell am start -n com.jio.store/.MainActivity
  ```
* Install **Zee5**, **SonyLIV**, and other streaming apps directly from JioStore. They will launch and play with zero crashes.

### Solution 2: Install microG GmsCore Companion
If you prefer not using JioStore and wish to run standard Android TV APKs from APKMirror:
* Sideload **microG Companion / GmsCore** (`com.google.android.gms`).
* microG provides lightweight open-source stubs for Google Play Services and Firebase, preventing third-party TV APKs from crashing on startup.

### Solution 3: Direct Jio CDN URL Fetch & App Extraction
JioStore downloads its APK packages from Reliance Jio's public Akamai NetStorage CDNs (similar to firmware OTAs on `http://fota.slv.*.jiophone.net` and `akamaized.net`). Once the direct download link for an app is captured, the exact Jio-tailored APK can be fetched on PC and installed directly via standard `adb install <app>.apk`.

---

## 13. Community Credits & Source References

This toolkit builds upon discoveries and research from the open-source community:

* **OnlyTech Forums Community & stbuser88:**  
  * [Breaking - Jio STB Sideload Apps Successfully (Thread)](https://onlytech.com/threads/jio-stb-sideload-apps-successfully.42903/page-7#post-722045)  
  * Special thanks to **stbuser88** for dumping the eMMC of the `JHSC200v3` and revealing the 39 official internal OTA URLs across Franklin, SDMC, MSTB, and Curie platforms.
* **GaneshT2305/jiostb-setup:**  
  * [GitHub Repository: GaneshT2305/jiostb-setup](https://github.com/GaneshT2305/jiostb-setup)  
  * Discovered the Jio `PackageManagerService` `Relax SCAN_REQUIRE_KNOWN` reboot-persistence quirk (`pm uninstall --user 0`), JioTV+ v6 split APK setup, and Kodi EPG automation.
* **ilikechocopies/sideload-jiostb:**  
  * [GitHub Repository: ilikechocopies/sideload-jiostb](https://github.com/ilikechocopies/sideload-jiostb)  
  * Pioneer in demonstrating early Docker/Technitium TR-069 ACS interception on Jio STBs.
