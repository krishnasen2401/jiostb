"""
Jio STB 1-Click Post-ADB Setup & Debloater Tool
Automates complete lockdown, debloating, custom launcher deployment,
hotkey remapping, and system optimizations on unlocked Reliance Jio STBs.

Compatible with:
- JHS D200 v1 / v2 (SDMC / franklin / Amlogic S905X2)
- JHS C200 v1 / v2 / v3 (Skyworth)
- JHS B200 / JMS B200A (Bluebank)
- Android 9 (TeleOS 1.x) & Android 11 (TeleOS 2.x)
"""

import os
import sys
import time
import json
import base64
import hashlib
import subprocess
import re

MANUFACTURER_KEYS = {
    "SDMC": "DahWaethuL9xoo3e",      # JHSD200, JMSD200, etc.
    "Bluebank": "Hee4Xeigaethaeye",  # JHSB200, JMSB200, etc.
    "Skyworth": "Rov5Ifozoobeeth8",  # JHSC200, JMSC200, etc.
}

# Essential bloatware to disable/freeze (Safe for all models)
SAFE_DEBLOAT_PACKAGES = [
    # Iwedia OTA updaters (Freezes background OTAs on JHS series)
    "com.iwedia.updateservice",
    "com.iwedia.httpupdate",
    "com.iwedia.pvodupdateservice",
    "com.iwedia.updatercuotaservice",
    # Jio FOTA updaters (Freezes background OTAs on JMS series: JMSC200, JMSD200, JMSB200)
    "com.jio.httpupdate",
    "com.jio.usbupdate",
    "com.rjil.jio.stb.commandreceiver",
    # Jio Ads & Content injection
    "com.jio.stbadservice",
    "com.jio.bioscopecontentservice",
    "com.jio.screensaver",
    # Telemetry, trackers & background schedulers
    "com.jio.jiobackgroundscheduler",
    "com.jio.backgroundscheduler",
    "com.jio.appoptimizer",
    "com.jio.adc.embedded",
    "com.jio.adc.aka",
    "com.jio.systemstats",
    "com.rjil.jiostblogservice",
    "com.jio.stb.remotediagnose",
    "com.jio.universalsetup",
    "com.netflix.partnertoken",
    # NOTE: com.jio.store is intentionally EXCLUDED from debloat
    # because Jio STBs lack Google Play Services (GMS). JioStore provides
    # official GMS-independent builds of Zee5, SonyLIV, SunNXT, etc.
]

# Packages that must NEVER be disabled on JHS/JMS boxes
PROTECTED_PACKAGES = [
    "com.jio.tr069client",       # Keeps TCP 5555 ADB alive on boot!
    "com.media.jio.sso.stb",     # Required for JioTV+ & LiveTV login!
    "com.jio.store",             # Required for non-GMS TV apps (Zee5, SonyLIV)!
]

def get_adb_binary():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    local_adb = os.path.join(base_dir, "bin", "adb.exe")
    if os.path.exists(local_adb):
        return local_adb
    return "adb"

ADB_BIN = get_adb_binary()

def run_adb(cmd, timeout=10):
    try:
        full_cmd = [ADB_BIN] + cmd if isinstance(cmd, list) else f'"{ADB_BIN}" {cmd}'
        res = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout, shell=not isinstance(cmd, list))
        return res.stdout.strip()
    except Exception as e:
        return ""

def run_adb_shell(shell_cmd, timeout=10):
    return run_adb(["shell", shell_cmd], timeout=timeout)

def is_package_enabled(pkg):
    res = run_adb_shell(f"pm list packages -e {pkg}")
    return any(line.strip() == f"package:{pkg}" for line in res.splitlines())

def is_package_disabled(pkg):
    res = run_adb_shell(f"pm list packages -d {pkg}")
    return any(line.strip() == f"package:{pkg}" for line in res.splitlines())

def is_package_installed(pkg):
    res = run_adb_shell(f"pm list packages {pkg}")
    return any(line.strip() == f"package:{pkg}" for line in res.splitlines())

def get_installed_packages():
    """Returns a set of all package names installed on the device (including uninstalled system packages)."""
    res = run_adb_shell("pm list packages -u")
    pkgs = set()
    for line in res.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            pkgs.add(line[8:].strip())
    return pkgs

def get_installed_home_packages():
    """Dynamically finds all packages on the device that declare android.intent.category.HOME."""
    out = run_adb_shell("cmd package query-activities -a android.intent.action.MAIN -c android.intent.category.HOME")
    home_pkgs = set()
    for line in out.splitlines():
        line = line.strip()
        m = re.search(r'([a-zA-Z0-9_\.]+)/[a-zA-Z0-9_\.]+', line)
        if m:
            pkg = m.group(1)
            if pkg not in ["com.spocky.projengmenu", "com.klevico.monet", "com.atroc.tvhome"]:
                home_pkgs.add(pkg)
    # Also include known stock launcher candidates if present on this hardware model
    known_candidates = [
        "com.iwedia.ui.rjio.launcher.reliance",
        "com.jio.media.stblauncher",
        "com.jio.jiolauncher",
        "com.google.android.tvlauncher",
        "com.jio.media.ondemand",
    ]
    installed = get_installed_packages()
    for k in known_candidates:
        if k in installed:
            home_pkgs.add(k)
    return home_pkgs

def check_connection():
    devs = run_adb(["devices"])
    lines = [line.strip() for line in devs.splitlines() if line.strip()]
    active_devices = [l for l in lines[1:] if "device" in l and "offline" not in l and "unauthorized" not in l]
    return len(active_devices) > 0

def get_candidate_ips():
    candidates = ["192.168.50.2"]
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_acs.log")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as lf:
                lines = lf.readlines()[-200:]
            for line in reversed(lines):
                m = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):\d+", line)
                if m:
                    ip = m.group(1)
                    if not ip.startswith("127.") and ip not in candidates:
                        candidates.append(ip)
        except Exception:
            pass
    return candidates

def connect_device():
    if check_connection():
        return True

    # Automatically probe discovered candidate IPs from lab and mock_acs.log
    candidates = get_candidate_ips()
    for ip in candidates:
        target = f"{ip}:5555"
        print(f"[*] Probing ADB at {target}...", end=" ", flush=True)
        run_adb(["connect", target])
        time.sleep(1.5)
        if check_connection():
            print("CONNECTED!")
            return True
        print("Not reached")

    print("\n[!] No active ADB device found.")
    print("    If your STB is on Wi-Fi/Ethernet, enter its IP address below:")
    ip = input("    STB IP address (e.g. 192.168.29.10) [Enter to skip]: ").strip()
    if not ip:
        return False

    target = f"{ip}:5555" if ":" not in ip else ip
    print(f"[*] Connecting to {target}...")
    run_adb(["connect", target])
    time.sleep(2)
    return check_connection()

def detect_device_info():
    model = run_adb_shell("getprop ro.product.model")
    device = run_adb_shell("getprop ro.product.device")
    manufacturer = run_adb_shell("getprop ro.product.manufacturer")
    build_id = run_adb_shell("getprop ro.build.display.id")
    serial = run_adb_shell("getprop ro.serialno")
    if not serial:
        serial = run_adb(["get-serialno"])
    acsdata = run_adb_shell("getprop ro.acsdata") or "9e434fa86d4f6ac7"

    combined = f"{model} {device} {manufacturer}".upper()
    if any(k in combined for k in ["JHSD", "JMSD", "SDMC"]):
        vendor = "SDMC"
    elif any(k in combined for k in ["JHSC", "JMSC", "SKYWORTH"]):
        vendor = "Skyworth"
    elif any(k in combined for k in ["JHSB", "JMSB", "BLUEBANK"]):
        vendor = "Bluebank"
    else:
        vendor = "SDMC"

    return {
        "model": model or "JioSTB",
        "device": device or "unknown",
        "manufacturer": manufacturer or "Reliance Jio",
        "vendor": vendor,
        "build_id": build_id or "unknown",
        "serial": serial or "unknown",
        "acsdata": acsdata
    }

def step_debloat():
    print("\n" + "=" * 60)
    print("  STEP 1: Freezing OTA Updaters & Disabling Jio Ads / Telemetry")
    print("=" * 60)

    installed = get_installed_packages()

    for pkg in SAFE_DEBLOAT_PACKAGES:
        if pkg not in installed:
            # Normal: different hardware models (JMSC vs JHSD vs JHSB) ship different packages
            continue

        print(f"  [-] Disabling {pkg}...", end=" ", flush=True)
        try:
            run_adb_shell(f"pm suspend --user 0 {pkg}")
        except Exception: pass
        out = run_adb_shell(f"pm disable-user --user 0 {pkg}")
        try:
            run_adb_shell(f"am force-stop {pkg}")
        except Exception: pass
        if "disabled" in out.lower() or "new state" in out.lower():
            print("OK")
        else:
            print("OK (suspended)")

    # Clear OTA download caches (safe if package not present on this model)
    for ota_pkg in ["com.iwedia.httpupdate", "com.iwedia.updateservice", "com.jio.httpupdate", "com.jio.usbupdate"]:
        if ota_pkg in installed:
            try: run_adb_shell(f"pm clear {ota_pkg}")
            except Exception: pass

    print("[+] OTA Updaters frozen. Your box will NEVER auto-update or lose ADB!")

    # Preserve and re-enable JioStore if present
    if "com.jio.store" in installed:
        try: run_adb_shell(f"pm unsuspend --user 0 com.jio.store")
        except Exception: pass
        run_adb_shell("pm enable com.jio.store")
        print("[+] JioStore preserved/active (Required for official non-GMS Zee5, SonyLIV, SunNXT).")

def enable_accessibility_service(service_name):
    """Safely appends an accessibility service without overwriting or disabling existing services."""
    cur_a11y = run_adb_shell("settings get secure enabled_accessibility_services").strip()
    services = [s.strip() for s in cur_a11y.split(":") if s.strip() and s.strip() != "null"] if cur_a11y else []
    if service_name not in services:
        services.append(service_name)
    new_a11y = ":".join(services)
    run_adb_shell("settings put secure accessibility_enabled 0")
    run_adb_shell(f'settings put secure enabled_accessibility_services "{new_a11y}"')
    run_adb_shell("settings put secure accessibility_enabled 1")
    return new_a11y

def disable_accessibility_service(service_name):
    """Safely removes an accessibility service from enabled_accessibility_services."""
    cur_a11y = run_adb_shell("settings get secure enabled_accessibility_services").strip()
    services = [s.strip() for s in cur_a11y.split(":") if s.strip() and s.strip() != "null"] if cur_a11y else []
    if service_name in services:
        services.remove(service_name)
    new_a11y = ":".join(services) if services else "null"
    run_adb_shell(f'settings put secure enabled_accessibility_services "{new_a11y}"')

def step_install_apks():
    print("\n" + "=" * 60)
    print("  STEP 2: Installing Essential Bundled Utilities")
    print("=" * 60)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    apks_dir = os.path.join(base_dir, "apks")

    if not os.path.exists(apks_dir):
        print(f"[-] Directory {apks_dir} not found. Skipping APK installation.")
        return

    apk_files = [
        ("Projectivy Launcher (Premium Leanback UI)", "ProjectivyLauncher.apk"),
        ("Monet Launcher (Clean Ad-free UI)", "monet-launcher.apk"),
        ("TV Home (Fast Leanback TV Launcher with HomeKeeper)", "TVHome.apk"),
        ("Key Mapper (Open-Source Button Remapper)", "KeyMapper.apk"),
        ("OpenShelf (FOSS Android TV App Store)", "OpenShelf-0.7.0.apk"),
        ("Shevery (On-device Shizuku shell)", "shevery-release.apk"),
        ("Google Cast Receiver (Official Chromecast)", "mediashell.apk"),
        ("Aptoide TV (Android TV App Store)", "AptoideTV.apk"),
        ("TV Bro (TV Web Browser & Downloader)", "TVBro.apk"),
        ("SmartTube ATV Bridge (YouTube Remote Bridge)", "stn_bridge_atv.apk"),
        ("Android TV Settings Shortcut", "AndroidSettingsShortcut.apk"),
        ("Jio Settings Shortcut", "JioSettingsShortcut.apk"),
        ("MicBridge (Voice Input for Sideloaded Apps)", "micbridge.apk"),
    ]

    for label, filename in apk_files:
        path = os.path.join(apks_dir, filename)
        if not os.path.exists(path):
            continue

        print(f"  [*] Installing {label}...", end=" ", flush=True)
        res = run_adb(["install", "-r", path], timeout=35)
        if "Success" in res:
            print("SUCCESS")
        else:
            print(f"FAILED ({res})")

    # Pre-grant installer permissions and secure settings
    run_adb_shell("appops set io.github.wingedpanther.openshelf REQUEST_INSTALL_PACKAGES allow")
    run_adb_shell("appops set cm.aptoidetv.pt REQUEST_INSTALL_PACKAGES allow")
    run_adb_shell("appops set com.phlox.tvwebbrowser REQUEST_INSTALL_PACKAGES allow")
    run_adb_shell("pm grant io.github.sds100.keymapper android.permission.WRITE_SECURE_SETTINGS")
    run_adb_shell("pm grant com.spocky.projengmenu android.permission.WRITE_SECURE_SETTINGS")
    run_adb_shell("pm grant com.klevico.monet android.permission.WRITE_SECURE_SETTINGS")
    run_adb_shell("pm grant com.atroc.tvhome android.permission.WRITE_SECURE_SETTINGS")
    run_adb_shell("appops set com.atroc.tvhome SYSTEM_ALERT_WINDOW allow")

    # Enable MicBridge accessibility service safely if installed
    mb_check = run_adb_shell("pm list packages dev.dedsec.micbridge")
    if "dev.dedsec.micbridge" in mb_check:
        enable_accessibility_service("dev.dedsec.micbridge/.MicA11yService")

def step_configure_launcher():
    print("\n" + "=" * 60)
    print("  STEP 3: Configuring Default Launcher & Bypassing PMS Reboot Bug")
    print("=" * 60)

    print("\n  Select your preferred default launcher:")
    print("    [1] Projectivy Launcher (Recommended - Premium Leanback UI, Channels & Up Next)")
    print("    [2] Monet Launcher (Lightweight Minimalist Material UI)")
    print("    [3] TV Home Launcher (Fast Lightweight Leanback TV UI with HomeKeeper)")
    print("    [4] Keep Current Launcher (Skip)")
    choice = input("  Enter choice [1, 2, 3, or 4, default 1]: ").strip()

    if choice == "4":
        print("  [*] Keeping current launcher configuration.")
        return "com.spocky.projengmenu"

    print("  [*] Detecting active stock launchers on this box...")
    stock_launchers = get_installed_home_packages()

    if stock_launchers:
        for s_pkg in stock_launchers:
            print(f"  [-] Deactivating stock launcher: {s_pkg}...")
            # 1. Suspend app (persists across reboots)
            try: run_adb_shell(f"pm suspend --user 0 {s_pkg}")
            except Exception: pass
            # 2. Disable app for user 0
            try: run_adb_shell(f"pm disable-user --user 0 {s_pkg}")
            except Exception: pass
            # 3. Uninstall for user 0 (bypasses Jio's PMS Relax SCAN_REQUIRE_KNOWN re-activation)
            try: run_adb_shell(f"pm uninstall --user 0 {s_pkg}")
            except Exception: pass
            # 4. Clear data & stop process
            try: run_adb_shell(f"pm clear {s_pkg}")
            except Exception: pass
            try: run_adb_shell(f"am force-stop {s_pkg}")
            except Exception: pass
    else:
        print("  [+] No active stock launchers detected.")

    # Also freeze Jio background watchdogs that attempt to restore the stock launcher
    installed = get_installed_packages()
    watchdog_pkgs = [
        "com.jio.stbadservice",
        "com.jio.appoptimizer",
        "com.jio.jiobackgroundscheduler",
        "com.jio.backgroundscheduler",
        "com.jio.screensaver",
        "com.jio.bioscopecontentservice"
    ]
    for w_pkg in watchdog_pkgs:
        if w_pkg in installed:
            try: run_adb_shell(f"pm suspend --user 0 {w_pkg}")
            except Exception: pass
            try: run_adb_shell(f"pm disable-user --user 0 {w_pkg}")
            except Exception: pass
            try: run_adb_shell(f"am force-stop {w_pkg}")
            except Exception: pass

    if choice == "2":
        launcher_pkg = "com.klevico.monet"
        print("  [*] Setting Monet Launcher as default Home activity...")
        run_adb_shell("cmd package set-home-activity com.klevico.monet/.HomeActivity")
        run_adb_shell("pm grant com.klevico.monet android.permission.WRITE_SECURE_SETTINGS")
        enable_accessibility_service("com.klevico.monet/.LauncherAccessibilityService")
        run_adb_shell("am start -n com.klevico.monet/.HomeActivity")
        print("[+] Monet Launcher activated and running on TV screen!")
    elif choice == "3":
        launcher_pkg = "com.atroc.tvhome"
        print("  [*] Setting TV Home Launcher as default Home activity...")
        run_adb_shell("cmd package set-home-activity com.atroc.tvhome/.MainActivity")
        run_adb_shell("pm grant com.atroc.tvhome android.permission.WRITE_SECURE_SETTINGS")
        run_adb_shell("appops set com.atroc.tvhome SYSTEM_ALERT_WINDOW allow")
        enable_accessibility_service("com.atroc.tvhome/.HomeKeeper")
        run_adb_shell("am start -n com.atroc.tvhome/.MainActivity")
        print("[+] TV Home Launcher activated and running on TV screen!")
    else:
        launcher_pkg = "com.spocky.projengmenu"
        print("  [*] Setting Projectivy Launcher as default Home activity...")
        run_adb_shell("cmd package set-home-activity com.spocky.projengmenu/.ui.home.MainActivity")
        run_adb_shell("pm grant com.spocky.projengmenu android.permission.WRITE_SECURE_SETTINGS")
        run_adb_shell("appops set com.spocky.projengmenu SYSTEM_ALERT_WINDOW allow")
        enable_accessibility_service("com.spocky.projengmenu/.services.ProjectivyAccessibilityService")
        run_adb_shell("am start -n com.spocky.projengmenu/.ui.home.MainActivity")
        print("[+] Projectivy Launcher activated and running on TV screen!")

    return launcher_pkg

def step_configure_hotkeys(launcher_pkg="com.spocky.projengmenu"):
    print("\n" + "=" * 60)
    print("  STEP 4: Configuring Remote Hotkeys")
    print("=" * 60)

    # Check if CleanYourTV (com.gathin.tvhome) is installed on the box
    installed = run_adb_shell("pm list packages com.gathin.tvhome")
    if "com.gathin.tvhome" in installed:
        config_data = {
            "keys": [
                {"keyCode": 137, "action": "launch_app", "packageName": launcher_pkg},
                {"keyCode": 138, "action": "launch_app", "packageName": "cm.aptoidetv.pt"},
                {"keyCode": 134, "action": "launch_app", "packageName": "com.user.androidsettings"},
                {"keyCode": 141, "action": "launch_app", "packageName": "com.jio.media.jiotvplus"},
                {"keyCode": 142, "action": "launch_app", "packageName": "com.hamondev.shevery"}
            ]
        }

        tmp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_tmp.json")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)

        remote_dir = "/sdcard/Android/data/com.gathin.tvhome/files"
        run_adb_shell(f"mkdir -p {remote_dir}")
        run_adb(["push", tmp_path, f"{remote_dir}/config.json"])
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        # Enable TVHome accessibility service safely without overwriting other services
        enable_accessibility_service("com.gathin.tvhome/.InputKeyService")
        run_adb_shell("am force-stop com.gathin.tvhome")
        print("[+] CleanYourTV hotkeys mapped (Netflix -> Launcher, Hotstar -> Aptoide TV, etc.)")
    else:
        print(f"[*] CleanYourTV key remapper not detected. Remote Home key is natively bound to {launcher_pkg}.")
    print("[+] Raw Mic key (231) preserved for native Bluetooth voice stack!")

def step_system_tweaks():
    print("\n" + "=" * 60)
    print("  STEP 5: Applying System UI & Visual Optimizations")
    print("=" * 60)

    print("  [*] Bypassing Setup Wizards & marking device as provisioned...")
    run_adb_shell("settings put secure user_setup_complete 1")
    run_adb_shell("settings put global device_provisioned 1")

    print("  [*] Enforcing Permanent Dark Mode across all menus...")
    run_adb_shell("cmd uimode night yes")
    run_adb_shell("settings put secure ui_night_mode 2")

    print("  [*] Optimizing Window Animation Scales for snappy navigation...")
    run_adb_shell("settings put global window_animation_scale 0.75")
    run_adb_shell("settings put global transition_animation_scale 0.75")
    run_adb_shell("settings put global animator_duration_scale 0.75")
    print("[+] Setup bypassed, dark mode and UI acceleration enabled!")

def step_save_credentials(dev_info):
    print("\n" + "=" * 60)
    print("  STEP 6: Saving TR-069 Credentials Profile")
    print("=" * 60)

    sk = MANUFACTURER_KEYS.get(dev_info["vendor"], MANUFACTURER_KEYS["SDMC"])
    combined = (dev_info["acsdata"] + sk).encode("utf-8")
    pw = base64.b64encode(hashlib.sha256(combined).digest()[:16]).decode("utf-8").strip()

    all_pw = {v: base64.b64encode(hashlib.sha256((dev_info["acsdata"] + k).encode("utf-8")).digest()[:16]).decode("utf-8").strip()
              for v, k in MANUFACTURER_KEYS.items()}

    creds = {
        "serial_number": dev_info["serial"],
        "ro_acsdata": dev_info["acsdata"],
        "vendor": dev_info["vendor"],
        "secret_key": sk,
        "cpe_password": pw,
        "all_vendor_passwords": all_pw,
        "model": dev_info["model"],
        "device": dev_info["device"],
        "software_version": dev_info["build_id"]
    }

    out_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "device_credentials.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(creds, f, indent=2)

    print(f"[+] Credentials saved to: {out_file}")
    print(f"[+] Derived Password ({dev_info['vendor']}): {pw}")
    print("[+] You can now query Jio ACS directly anytime via QUERY_JIO_ACS.bat!")

def step_manage_jiostore_apps():
    print("\n" + "=" * 60)
    print("  JIOSTORE & NON-GMS APP MANAGEMENT (Zee5, SonyLIV, Hotstar)")
    print("=" * 60)
    print("  The Non-GMS Problem:")
    print("  * Jio STBs run AOSP without Google Play Services (GMS).")
    print("  * Generic TV APKs from APKMirror or Play Store crash on startup")
    print("    because they call 'com.google.android.gms' APIs.")
    print("  * JioStore ('com.jio.store') distributes custom AOSP builds that")
    print("    run without GMS, but JioStore can silently push unwanted bloat")
    print("    and casual games in the background if left running indefinitely.")
    print("  * NOTE ON OTT SUBSCRIPTIONS: Bundled JioFiber OTT apps (Hotstar, Zee5,")
    print("    SonyLIV) require a periodic weekly heartbeat through JioStore / TR-069")
    print("    to refresh subscriber plan tokens. Do not permanently nuke them!")
    print("\n  Recommended Solutions:")
    print("  [1] Install & Freeze Workflow (Best of both worlds!)")
    print("      (Temporarily enables JioStore -> You install Zee5/SonyLIV ->")
    print("       Press Enter -> JioStore is frozen so it CANNOT auto-install bloat)")
    print("  [2] Enable JioStore permanently (Keep running in background)")
    print("  [3] Disable / Freeze JioStore (Blocks all background auto-installs & bloat)")
    print("  [4] microG GmsCore Instructions (Run generic APKMirror apps without crashes)")
    print("  [5] Return to Main Menu")

    sub_choice = input("\nEnter choice [1-5, default: 1]: ").strip()
    if not sub_choice or sub_choice == "1":
        print("  [*] Enabling com.jio.store...")
        run_adb_shell("pm enable com.jio.store")
        print("  [*] Launching JioStore on TV screen...")
        run_adb_shell("am start -n com.jio.store/.MainActivity")
        print("\n  >> Action on your TV: Use your remote to install your desired apps (Zee5, SonyLIV, etc.) <<")
        input("  >> Once finished installing, press Enter here to immediately re-freeze JioStore... << ")
        print("  [*] Freezing JioStore to prevent background bloatware and auto-installs...")
        run_adb_shell("pm disable-user --user 0 com.jio.store")
        run_adb_shell("am force-stop com.jio.store")
        print("[+] SUCCESS: JioStore frozen! Your installed apps will work permanently with zero bloat!")
    elif sub_choice == "2":
        run_adb_shell("pm enable com.jio.store")
        print("[+] JioStore permanently enabled.")
    elif sub_choice == "3":
        run_adb_shell("pm disable-user --user 0 com.jio.store")
        run_adb_shell("am force-stop com.jio.store")
        print("[+] JioStore disabled. All background app pushes and telemetry blocked.")
    elif sub_choice == "4":
        print("\n  --- microG Companion (GmsCore) Universal Fix ---")
        print("  1. Download the latest microG GmsCore APK from: https://microg.org/download.html")
        print("  2. Install via ADB: adb install -r com.google.android.gms-*.apk")
        print("  3. microG provides dummy open-source stubs for Google Play Services.")
        print("  4. Once installed, ANY generic TV APK from APKMirror/Aptoide TV")
        print("     (Zee5, SonyLIV, Hotstar, YouTube) will launch without crashing!")
        input("\n  Press Enter to return...")
    else:
        print("[*] Returning to main menu.")

def step_package_manager():
    while True:
        print("\n" + "=" * 65)
        print("  PACKAGE MANAGER: Enable / Disable Control Center")
        print("=" * 65)
        print("  [1] Freeze / Disable ALL Bloatware Packages (Safe Debloat)")
        print("  [2] Unfreeze / Enable ALL Stock Packages (Restore all services)")
        print("  [3] Toggle JioStore (com.jio.store)")
        print("  [4] Toggle TR-069 Client (com.jio.tr069client) [Required for ADB on JHS!]")
        print("  [5] Toggle Jio Voice Assistant (com.android.app.jio.voiceassist)")
        print("  [6] Scan & Show Status of all Jio/Iwedia packages")
        print("  [7] On-Device Shizuku + Hail/Canta TV Management Guide (No PC needed)")
        print("  [8] Return to Main Menu")

        sub = input("\nEnter choice [1-8, default: 8]: ").strip()
        if not sub or sub == "8":
            break

        if sub == "1":
            print("\n  [*] Freezing all bloatware packages...")
            for pkg in SAFE_DEBLOAT_PACKAGES:
                run_adb_shell(f"pm disable-user --user 0 {pkg}")
            print("  [+] All bloatware packages disabled successfully!")
        elif sub == "2":
            print("\n  [*] Unfreezing all stock packages...")
            for pkg in SAFE_DEBLOAT_PACKAGES:
                run_adb_shell(f"pm enable {pkg}")
            run_adb_shell("pm enable com.jio.store")
            run_adb_shell("pm enable com.jio.tr069client")
            run_adb_shell("pm enable com.android.app.jio.voiceassist")
            print("  [+] All stock packages re-enabled successfully!")
        elif sub == "3":
            pkg = "com.jio.store"
            if is_package_disabled(pkg):
                print(f"  [*] Enabling {pkg}...")
                run_adb_shell(f"pm enable {pkg}")
                print(f"  [+] {pkg} is now ENABLED.")
            else:
                print(f"  [*] Freezing {pkg}...")
                run_adb_shell(f"pm disable-user --user 0 {pkg}")
                run_adb_shell(f"am force-stop {pkg}")
                print(f"  [+] {pkg} is now DISABLED (Frozen).")
        elif sub == "4":
            pkg = "com.jio.tr069client"
            if is_package_disabled(pkg):
                print(f"  [*] Enabling {pkg}...")
                run_adb_shell(f"pm enable {pkg}")
                print(f"  [+] {pkg} is now ENABLED.")
            else:
                print("\n  [!] CRITICAL WARNING FOR JHS BOXES (JHSC200 / JHSD200):")
                print("      com.jio.tr069client sets 'service.adb.tcp.port=5555' at boot.")
                print("      Disabling it may cause ADB network access to drop after reboot!")
                confirm = input("      Are you sure you want to disable com.jio.tr069client? [y/N]: ").strip().lower()
                if confirm == "y":
                    run_adb_shell(f"pm disable-user --user 0 {pkg}")
                    run_adb_shell(f"am force-stop {pkg}")
                    print(f"  [+] {pkg} is now DISABLED.")
                else:
                    print("  [*] Cancelled. Keeping com.jio.tr069client enabled.")
        elif sub == "5":
            pkg = "com.android.app.jio.voiceassist"
            if is_package_disabled(pkg):
                print(f"  [*] Enabling {pkg}...")
                run_adb_shell(f"pm enable {pkg}")
                print(f"  [+] {pkg} is now ENABLED.")
            else:
                print(f"  [*] Disabling {pkg}...")
                run_adb_shell(f"pm disable-user --user 0 {pkg}")
                run_adb_shell(f"am force-stop {pkg}")
                print(f"  [+] {pkg} is now DISABLED.")
        elif sub == "6":
            print("\n  [*] Querying package status on STB...")
            packages_to_check = SAFE_DEBLOAT_PACKAGES + [
                "com.jio.store",
                "com.jio.tr069client",
                "com.android.app.jio.voiceassist",
                "com.media.jio.sso.stb",
                "com.iwedia.ui.rjio.launcher.reliance"
            ]
            print(f"\n  {'PACKAGE NAME':<42} {'STATUS'}")
            print("  " + "-" * 57)
            for pkg in packages_to_check:
                if is_package_disabled(pkg):
                    status = "[DISABLED / FROZEN]"
                elif is_package_enabled(pkg):
                    status = "[ENABLED / ACTIVE]"
                elif is_package_installed(pkg):
                    status = "[INSTALLED]"
                else:
                    status = "[NOT PRESENT / UNINSTALLED]"
                print(f"  {pkg:<42} {status}")
            input("\n  Press Enter to continue...")
        elif sub == "7":
            print("\n  " + "=" * 60)
            print("  SHIZUKU / SHEVERY ON-DEVICE PACKAGE MANAGEMENT GUIDE")
            print("  " + "=" * 60)
            print("  You do NOT need a PC to freeze or unfreeze apps every week!")
            print("  You can do it directly from your TV sofa using your remote:")
            print("\n  1. Launch Shevery (Bundled in apks/shevery-release.apk):")
            print("     Shevery runs an on-device Shizuku ADB daemon with shell (uid=2000).")
            print("  2. Install 'Hail' or 'Canta' (Open-source App Freezers):")
            print("     - Hail is an open-source Android TV app freezer with full D-pad support.")
            print("     - In Hail settings, choose Working Mode: 'Shizuku'.")
            print("  3. Create App Tags / 1-Click Freezing on TV:")
            print("     - Add 'com.jio.store' to Hail.")
            print("     - Freeze JioStore when not in use to block bloat.")
            print("     - Unfreeze JioStore with 1 remote click when you need to install an app")
            print("       or refresh your weekly JioFiber OTT subscriptions!")
            print("  " + "=" * 60)
            input("\n  Press Enter to continue...")

def step_voice_troubleshoot():
    print("\n" + "=" * 65)
    print("  VOICE RECOGNITION & REMOTE DIAGNOSTIC / REPAIR TOOL")
    print("=" * 65)
    print("  Diagnosing Voice Assistant issues (Circle opens, but voice is null)...")

    # 1. Check Voice Recognition Services
    int_srv = run_adb_shell("settings get secure voice_interaction_service")
    rec_srv = run_adb_shell("settings get secure voice_recognition_service")
    print(f"\n  [*] Current voice_interaction_service: {int_srv or 'null / unset'}")
    print(f"  [*] Current voice_recognition_service: {rec_srv or 'null / unset'}")

    # 2. Check Package Status
    va_pkg = "com.android.app.jio.voiceassist"
    va_enabled = is_package_enabled(va_pkg)
    print(f"  [*] Jio Voice Assistant ({va_pkg}): {'ENABLED' if va_enabled else 'DISABLED/FROZEN'}")

    # 3. Check CleanYourTV mic interception
    print("\n  [*] Checking CleanYourTV / TVHome hotkey configuration...")
    clean_cfg = run_adb_shell("cat /sdcard/Android/data/com.gathin.tvhome/files/config.json")
    has_mic_intercept = ("231" in clean_cfg) or ("KEYCODE_VOICE_ASSIST" in clean_cfg) or ("84" in clean_cfg)
    if has_mic_intercept:
        print("  [!] WARNING: CleanYourTV is currently intercepting KeyCode 231 / Mic button!")
        print("      Intercepting KeyCode 231 breaks the Bluetooth Low Energy (BLE)")
        print("      GATT audio stream (ServiceBleVoiceRead), causing recognized text to be null.")
    else:
        print("  [+] CleanYourTV is NOT intercepting KeyCode 231 (Correct).")

    print("\n  Available Actions:")
    print("  [1] Apply Complete Voice Repair")
    print("      (Re-enable Voice Assistant + Grant Mic Permission + Restore Profile Providers + Reset Voice Service)")
    print("  [2] Install & Enable MicBridge (Mic Input Fix for Sideloaded Apps: SmartTube, Stremio, Kodi, etc.)")
    print("  [3] Bluetooth Remote BLE GATT Re-Pairing Instructions")
    print("  [4] Return to Main Menu")

    act = input("\nEnter choice [1-4, default: 1]: ").strip()
    if not act or act == "1":
        print("\n  [*] Applying Voice Repair...")
        run_adb_shell(f"pm enable {va_pkg}")
        run_adb_shell(f"pm grant {va_pkg} android.permission.RECORD_AUDIO")
        run_adb_shell("cmd package install-existing com.jio.profileutility")
        run_adb_shell("cmd package install-existing com.jio.universalsetup")
        run_adb_shell("settings put secure voice_recognition_service com.android.app.jio.voiceassist/.VoiceRecognitionService")
        run_adb_shell("settings put secure tts_default_synth com.svox.pico")

        if has_mic_intercept:
            print("  [*] Removing KeyCode 231 from CleanYourTV configuration...")
            try:
                cfg_obj = json.loads(clean_cfg)
                if "keys" in cfg_obj:
                    cfg_obj["keys"] = [k for k in cfg_obj["keys"] if k.get("keyCode") not in [231, 84]]
                if "keyMappings" in cfg_obj:
                    cfg_obj["keyMappings"] = [k for k in cfg_obj["keyMappings"] if k.get("keyCode") not in [231, 84]]
                tmp_cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_fixed.json")
                with open(tmp_cfg, "w", encoding="utf-8") as f:
                    json.dump(cfg_obj, f, indent=2)
                run_adb(f'push "{tmp_cfg}" /sdcard/Android/data/com.gathin.tvhome/files/config.json')
                if os.path.exists(tmp_cfg):
                    os.remove(tmp_cfg)
                print("  [+] KeyCode 231 removed from CleanYourTV.")
            except Exception as e:
                print(f"  [-] Note: Could not auto-edit CleanYourTV config: {e}")

        print("\n  [+] System settings updated successfully!")
        print("\n  [CRITICAL FINAL STEP: BLUETOOTH BLE AUDIO RE-PAIRING]")
        print("  Because the remote's BLE GATT audio stream was hung, you MUST re-pair the remote:")
        print("  1. Press and hold 'Back' + 'Menu' simultaneously on your Jio Remote for 5 seconds.")
        print("  2. The status LED on the remote will start blinking rapidly.")
        print("  3. On TV Settings -> Remotes & Accessories, select 'JioRemote' to re-pair.")
        print("  4. Press and hold the Mic button while speaking. Transcription will now work!")
        input("\n  Press Enter to continue...")
    elif act == "2":
        print("\n  [*] Installing & Enabling MicBridge for Sideloaded Apps...")
        apk_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apks", "micbridge.apk")
        if not os.path.exists(apk_path):
            print(f"  [-] Error: {apk_path} not found!")
            input("\n  Press Enter to continue...")
            return
        run_adb(f'install -r -g "{apk_path}"')
        enable_accessibility_service("dev.dedsec.micbridge/.MicA11yService")
        print("\n  [+] MicBridge installed and Accessibility Service enabled!")
        print("  How to use:")
        print("  1. Open any sideloaded app (SmartTube, Stremio, Kodi, TV Bro, etc.).")
        print("  2. Open its search box.")
        print("  3. Press the Mic button on the remote and speak.")
        print("  4. Jio voice overlay will capture speech, and MicBridge will auto-inject the text!")
        input("\n  Press Enter to continue...")
    elif act == "3":
        print("\n  --- BLUETOOTH BLE REMOTE RE-PAIRING GUIDE ---")
        print("  1. Press and hold 'Back' + 'Menu' simultaneously on your Jio Remote for 5 seconds.")
        print("  2. When the LED blinks, open Settings -> Remotes & Accessories on your TV.")
        print("  3. Re-pair 'JioRemote'. This resets the proprietary BLE GATT voice characteristics:")
        print("     - Service UUID: 8980f798-0614-11ea-8d71-362b9e155667")
        print("     - Audio Data:   8980f9fa-0614-11ea-8d71-362b9e155667")
        print("     - Audio Control:8980f9fb-0614-11ea-8d71-362b9e155667")
        input("\n  Press Enter to continue...")

def step_revert_stock():
    print("\n" + "=" * 60)
    print("  REVERT: Restoring Stock Jio Launcher & Services")
    print("=" * 60)

    print("  [*] Re-installing stock Jio launcher for user 0...")
    for s_pkg in ["com.iwedia.ui.rjio.launcher.reliance", "com.jio.media.stblauncher", "com.jio.jiolauncher"]:
        run_adb_shell(f"cmd package install-existing {s_pkg}")
        run_adb_shell(f"pm unsuspend --user 0 {s_pkg}")
        run_adb_shell(f"pm enable {s_pkg}")

    # Set default home to stock
    stock_home = run_adb_shell("cmd package resolve-activity -a android.intent.action.MAIN -c android.intent.category.HOME")
    for s_pkg in ["com.iwedia.ui.rjio.launcher.reliance", "com.jio.media.stblauncher", "com.jio.jiolauncher"]:
        if s_pkg in stock_home:
            run_adb_shell(f"cmd package set-home-activity {s_pkg}/.MainActivity")
            break

    print("  [*] Re-enabling Jio services...")
    for pkg in SAFE_DEBLOAT_PACKAGES:
        run_adb_shell(f"pm unsuspend --user 0 {pkg}")
        run_adb_shell(f"pm enable {pkg}")

    run_adb_shell("cmd uimode night no")
    run_adb_shell("settings put secure ui_night_mode 1")
    print("[+] Device restored to stock Jio configuration.")

def main():
    print("=" * 65)
    print("       Jio STB 1-Click Post-ADB Setup & Debloater Tool")
    print("=" * 65)

    if not connect_device():
        print("\n[-] Error: Could not establish ADB connection with STB.")
        print("    1. Ensure your STB is turned on and connected to the same network.")
        print("    2. Make sure ADB was already unlocked (e.g. via UNLOCK_ADB_ETHERNET.bat).")
        print("    3. Run: adb connect <STB_IP>:5555")
        input("\nPress Enter to exit...")
        sys.exit(1)

    info = detect_device_info()
    print("\n[+] STB Connected Successfully:")
    print(f"    - Model:        {info['model']} ({info['device']})")
    print(f"    - Manufacturer: {info['manufacturer']} [Vendor: {info['vendor']}]")
    print(f"    - Build:        {info['build_id']}")
    print(f"    - Serial:       {info['serial']}")

    print("\nSelect Action:")
    print("  1) Full 1-Click Setup (Recommended)")
    print("     [Freeze OTAs + Debloat Ads + Choose Projectivy/Monet + Dark Mode + Hotkeys]")
    print("  2) Debloat & Freeze OTAs Only (Keep current launcher & apps)")
    print("  3) Install Bundled Utility APKs Only")
    print("  4) Configure Launcher & Remote Hotkeys Only")
    print("  5) Manage JioStore & Non-GMS Apps (Fix Zee5/SonyLIV crashes)")
    print("  6) Package Manager & Toggle Center (Enable/Disable for All or Individual)")
    print("  7) Voice Recognition & Remote Diagnostic / Repair Tool")
    print("  8) Revert / Restore Stock Jio Launcher & Services")
    print("  9) Exit")

    choice = input("\nEnter choice [1-9, default: 1]: ").strip()
    if not choice:
        choice = "1"

    if choice == "1":
        step_debloat()
        step_install_apks()
        chosen_launcher = step_configure_launcher()
        step_configure_hotkeys(chosen_launcher)
        step_system_tweaks()
        step_save_credentials(info)
        print("\n" + "=" * 65)
        print("  [SUCCESS] 1-Click Post-ADB Setup Completed Successfully!")
        print("  Your Jio STB is now fully debloated, ad-free, and customized.")
        print("=" * 65)
    elif choice == "2":
        step_debloat()
        step_save_credentials(info)
    elif choice == "3":
        step_install_apks()
    elif choice == "4":
        chosen_launcher = step_configure_launcher()
        step_configure_hotkeys(chosen_launcher)
        step_system_tweaks()
    elif choice == "5":
        step_manage_jiostore_apps()
    elif choice == "6":
        step_package_manager()
    elif choice == "7":
        step_voice_troubleshoot()
    elif choice == "8":
        step_revert_stock()
    elif choice == "9":
        print("Exiting.")
        sys.exit(0)
    else:
        print("[!] Invalid option selected.")

    input("\nPress Enter to finish...")

if __name__ == "__main__":
    main()
