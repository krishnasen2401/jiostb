---
name: Bug Report / Unlock Assistance
about: Report an issue or error when unlocking ADB, capturing firmware, or querying ACS
title: "[ISSUE]: "
labels: ["bug", "triage"]
assignees: ''
---

### 1. Device & Setup Information
- **Jio STB Model:** (e.g., `JHSD200 v2/v5`, `JHSC200`, `JMSD200A`, `JMSC200A`, `JMSB200A`)
- **Firmware Version:** (e.g., `11.3.46`, `25.1.9`, `5.7.1`, or check under TV Settings -> About)
- **Script Used:** (e.g., `UNLOCK_ADB_ETHERNET.bat`, `UNLOCK_ADB_WIFI.bat`, `CAPTURE_FIRMWARE_ETHERNET.bat`)
- **Model Selected at Prompt:** `[1] JMS Series` OR `[2] JHS Series`
- **Host Operating System:** Windows 11 / Windows 10

---

### 2. Pre-Submission Checklist
*(Please verify each item before opening an issue)*
- [ ] **Physical Cold Reboot:** I physically unplugged the 12V power adapter from the back of the STB (not just standby with remote), waited 5 seconds, and reconnected.
- [ ] **Patience Window (60–90s):** I left the lab terminal windows open and running for at least 1–2 minutes after boot (TR-069 `com.jio.tr069client` only initializes 45–60 seconds after power-on).
- [ ] **PC Internet Active:** My PC/laptop is connected to Wi-Fi/Internet (required for Online Relay Mode with Jio ACS nonces).
- [ ] **STB Isolated:** The STB is connected ONLY to the PC (via direct RJ45 Ethernet or PC Hotspot), not to the home router.

---

### 3. Describe the Problem
A clear and concise description of the behavior you are seeing.

---

### 4. Console Log Snippet
```text
(Paste relevant lines from your command prompt window here)
```

---

### 5. Mandatory Diagnostic Logs
*(Please drag-and-drop or attach the 3 log files generated inside your `jio-fota-toolkit` folder)*
1. `mock_acs.log` (TLS handshakes and ports 443/8443/9443 status)
2. `captive_lab.log` (DHCP assignment, DNS spoofing, and NTP time sync)
3. `mock_acs_packets.log` (Decrypted TR-069 Inform & CWMP RPC exchanges)
