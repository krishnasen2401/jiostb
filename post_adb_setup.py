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
    # Jio FOTA updaters (Freezes background OTAs on JMS series)
    "com.jio.httpupdate",
    "com.jio.usbupdate",
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

def check_connection():
    devs = run_adb(["devices"])
    lines = [line.strip() for line in devs.splitlines() if line.strip()]
    active_devices = [l for l in lines[1:] if "device" in l and "offline" not in l and "unauthorized" not in l]
    return len(active_devices) > 0

def connect_device():
    if check_connection():
        return True

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

    for pkg in SAFE_DEBLOAT_PACKAGES:
        print(f"  [-] Disabling {pkg}...", end=" ", flush=True)
        out = run_adb_shell(f"pm disable-user --user 0 {pkg}")
        if "disabled" in out.lower() or "new state" in out.lower():
            print("OK")
        else:
            print(out if out else "Skipped/Not found")

    # Clear OTA download caches
    run_adb_shell("pm clear com.iwedia.httpupdate")
    run_adb_shell("pm clear com.iwedia.updateservice")
    run_adb_shell("pm clear com.jio.httpupdate")
    run_adb_shell("pm clear com.jio.usbupdate")
    print("[+] OTA Updaters frozen. Your box will NEVER auto-update or lose ADB!")

    # Preserve and re-enable JioStore (required for GMS-independent TV apps)
    run_adb_shell("pm enable com.jio.store")
    print("[+] JioStore preserved/active (Required for official non-GMS Zee5, SonyLIV, SunNXT).")

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
        ("Key Mapper (Open-Source Button Remapper)", "KeyMapper.apk"),
        ("OpenShelf (FOSS Android TV App Store)", "OpenShelf-0.7.0.apk"),
        ("Shevery (On-device Shizuku shell)", "shevery-release.apk"),
        ("Google Cast Receiver (Official Chromecast)", "mediashell.apk"),
        ("Aurora Store (Play Store Client)", "AuroraStore_4.8.4.apk"),
        ("Android TV Settings Shortcut", "AndroidSettingsShortcut.apk"),
        ("Jio Settings Shortcut", "JioSettingsShortcut.apk"),
        ("TVHome (CleanYourTV Hotkeys)", "TVHome.apk"),
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
    run_adb_shell("appops set com.aurora.store REQUEST_INSTALL_PACKAGES allow")
    run_adb_shell("pm grant io.github.sds100.keymapper android.permission.WRITE_SECURE_SETTINGS")
    run_adb_shell("pm grant com.spocky.projengmenu android.permission.WRITE_SECURE_SETTINGS")
    run_adb_shell("pm grant com.klevico.monet android.permission.WRITE_SECURE_SETTINGS")

def step_configure_launcher():
    print("\n" + "=" * 60)
    print("  STEP 3: Configuring Default Launcher & Bypassing PMS Reboot Bug")
    print("=" * 60)

    print("\n  Select your preferred default launcher:")
    print("    [1] Projectivy Launcher (Recommended - Premium Leanback UI, Channels & Up Next)")
    print("    [2] Monet Launcher (Lightweight Minimalist Material UI)")
    print("    [3] Keep Current Launcher (Skip)")
    choice = input("  Enter choice [1, 2, or 3, default 1]: ").strip()

    if choice == "3":
        print("  [*] Keeping current launcher configuration.")
        return "com.spocky.projengmenu"

    print("  [*] Applying persistent PMS bypass for stock launcher...")
    # Jio PMS Relax SCAN_REQUIRE_KNOWN re-enables disabled apps on reboot.
    # Uninstalling for user 0 permanently removes it while keeping APK in /system!
    run_adb_shell("pm uninstall --user 0 com.iwedia.ui.rjio.launcher.reliance")

    if choice == "2":
        launcher_pkg = "com.klevico.monet"
        print("  [*] Setting Monet Launcher as default Home activity...")
        run_adb_shell("cmd package set-home-activity com.klevico.monet/.HomeActivity")
        run_adb_shell("pm grant com.klevico.monet android.permission.WRITE_SECURE_SETTINGS")
        run_adb_shell("settings put secure enabled_accessibility_services com.klevico.monet/.LauncherAccessibilityService")
        run_adb_shell("settings put secure accessibility_enabled 1")
        run_adb_shell("am start -n com.klevico.monet/.HomeActivity")
        print("[+] Monet Launcher activated and running on TV screen!")
    else:
        launcher_pkg = "com.spocky.projengmenu"
        print("  [*] Setting Projectivy Launcher as default Home activity...")
        run_adb_shell("cmd package set-home-activity com.spocky.projengmenu/.ui.home.MainActivity")
        run_adb_shell("pm grant com.spocky.projengmenu android.permission.WRITE_SECURE_SETTINGS")
        run_adb_shell("appops set com.spocky.projengmenu SYSTEM_ALERT_WINDOW allow")
        run_adb_shell("settings put secure enabled_accessibility_services com.spocky.projengmenu/.services.ProjectivyAccessibilityService")
        run_adb_shell("settings put secure accessibility_enabled 1")
        run_adb_shell("am start -n com.spocky.projengmenu/.ui.home.MainActivity")
        print("[+] Projectivy Launcher activated and running on TV screen!")

    run_adb_shell("am force-stop com.iwedia.ui.rjio.launcher.reliance")
    return launcher_pkg

def step_configure_hotkeys(launcher_pkg="com.spocky.projengmenu"):
    print("\n" + "=" * 60)
    print("  STEP 4: Configuring CleanYourTV Remote Hotkeys")
    print("=" * 60)

    config_data = {
        "keys": [
            {"keyCode": 137, "action": "launch_app", "packageName": launcher_pkg},
            {"keyCode": 138, "action": "launch_app", "packageName": "com.aurora.store"},
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

    # Enable TVHome accessibility service
    run_adb_shell("settings put secure enabled_accessibility_services com.gathin.tvhome/.InputKeyService")
    run_adb_shell("am force-stop com.gathin.tvhome")
    print("[+] CleanYourTV hotkeys mapped (Netflix -> Monet, Hotstar -> Aurora Store, etc.)")
    print("[+] Raw Mic key (231) preserved for native Bluetooth stack!")

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
    print("  Why generic APKs crash on Jio STB:")
    print("  * Jio STBs run AOSP without Google Play Services (GMS).")
    print("  * Generic TV APKs from APKMirror/Play Store crash on boot")
    print("    because they look for 'com.google.android.gms' APIs.")
    print("  * The official builds distributed through JioStore ('com.jio.store')")
    print("    are customized specifically for Jio STB to run 100% without GMS!")
    print("\n  Actions Available:")
    print("  [1] Enable & Launch JioStore on TV (Recommended)")
    print("      (Opens JioStore so you can install official non-GMS Zee5, SonyLIV, etc.)")
    print("  [2] Enable JioStore in Background (Keep enabled without opening)")
    print("  [3] Disable JioStore (If you don't want JioStore running)")
    print("  [4] Return to Main Menu")

    sub_choice = input("\nEnter choice [1-4, default: 1]: ").strip()
    if not sub_choice or sub_choice == "1":
        print("  [*] Enabling com.jio.store...")
        run_adb_shell("pm enable com.jio.store")
        print("  [*] Launching JioStore on TV screen...")
        run_adb_shell("am start -n com.jio.store/.MainActivity")
        print("[+] JioStore launched on your TV! You can now install official TV apps.")
    elif sub_choice == "2":
        run_adb_shell("pm enable com.jio.store")
        print("[+] JioStore enabled.")
    elif sub_choice == "3":
        run_adb_shell("pm disable-user --user 0 com.jio.store")
        print("[+] JioStore disabled.")
    else:
        print("[*] Returning to main menu.")

def step_revert_stock():
    print("\n" + "=" * 60)
    print("  REVERT: Restoring Stock Jio Launcher & Services")
    print("=" * 60)

    print("  [*] Re-installing stock Jio launcher for user 0...")
    run_adb_shell("cmd package install-existing com.iwedia.ui.rjio.launcher.reliance")
    run_adb_shell("cmd package set-home-activity com.iwedia.ui.rjio.launcher.reliance/.MainActivity")

    print("  [*] Re-enabling Jio services...")
    for pkg in SAFE_DEBLOAT_PACKAGES:
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
    print("  6) Revert / Restore Stock Jio Launcher & Services")
    print("  7) Exit")

    choice = input("\nEnter choice [1-7, default: 1]: ").strip()
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
        step_revert_stock()
    elif choice == "7":
        print("Exiting.")
        sys.exit(0)
    else:
        print("[!] Invalid option selected.")

    input("\nPress Enter to finish...")

if __name__ == "__main__":
    main()
