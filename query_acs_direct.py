"""
Standalone Jio ACS Query Tool
Allows checking Jio TR-069 ACS for firmware updates and RPC commands
completely from the PC without requiring the physical STB.

CPE Credentials derived via reverse engineering of libtr069client & TR069ClientService:
- Username: Device Serial Number (from `getprop ro.serialno`)
- Prepassword: Device ro.acsdata (from `getprop ro.acsdata`)
- Native Secret Key (libcpe sk):
    * SDMC:     DahWaethuL9xoo3e
    * Bluebank: Hee4Xeigaethaeye
    * Skyworth: Rov5Ifozoobeeth8
- Derived Password: Base64(SHA256(prepassword + secret_key)[:16])

Run EXTRACT_CREDENTIALS.bat once while connected via ADB to generate device_credentials.json!
"""

import os
import json
import sys
import hashlib
import base64
import requests
from requests.auth import HTTPDigestAuth
import urllib3
urllib3.disable_warnings()

MANUFACTURER_KEYS = {
    "1": ("SDMC", "DahWaethuL9xoo3e"),
    "2": ("Bluebank", "Hee4Xeigaethaeye"),
    "3": ("Skyworth", "Rov5Ifozoobeeth8"),
}

REAL_ACS_URL = "https://49.40.134.113:8443/ftacs-digest/ACS"
REAL_ACS_HOST = "acs.oss.jio.com:8443"
SERIAL_NUMBER = None
CPE_PASSWORD = None
PRODUCT_CLASS = "JHSD200"

def derive_cpe_password(acsdata, secret_key):
    combined = (acsdata + secret_key).encode("utf-8")
    return base64.b64encode(hashlib.sha256(combined).digest()[:16]).decode("utf-8").strip()

# Check for local device credentials file
creds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "device_credentials.json")
if os.path.exists(creds_path):
    try:
        with open(creds_path, "r", encoding="utf-8") as f:
            creds = json.load(f)
            SERIAL_NUMBER = creds.get("serial_number")
            CPE_PASSWORD = creds.get("cpe_password")
            PRODUCT_CLASS = creds.get("model", PRODUCT_CLASS)
            vendor = creds.get("vendor", "SDMC")
            print(f"[i] Loaded credentials from device_credentials.json for {SERIAL_NUMBER} ({PRODUCT_CLASS} / {vendor})")
    except Exception as e:
        print(f"[!] Warning reading device_credentials.json: {e}")

if not SERIAL_NUMBER or not CPE_PASSWORD:
    print("=" * 60)
    print("  NO SAVED DEVICE CREDENTIALS FOUND (device_credentials.json)")
    print("  You can generate it automatically by connecting your STB via ADB")
    print("  and running: EXTRACT_CREDENTIALS.bat")
    print("=" * 60)
    s_input = input("Enter your STB Serial Number (or press Enter to exit): ").strip()
    if not s_input:
        sys.exit(0)
    acs_input = input("Enter ro.acsdata (press Enter for default '9e434fa86d4f6ac7'): ").strip()
    if not acs_input:
        acs_input = "9e434fa86d4f6ac7"
    
    print("\nSelect Manufacturer:")
    print("  1) SDMC     (JHSD200, JMSD200, etc.) [sk: DahWaethuL9xoo3e]")
    print("  2) Bluebank (JHSB200, JMSB200, etc.) [sk: Hee4Xeigaethaeye]")
    print("  3) Skyworth (JHSC200, JMSC200, etc.) [sk: Rov5Ifozoobeeth8]")
    choice = input("Choice [1/2/3, default: 1]: ").strip()
    vendor_name, sk = MANUFACTURER_KEYS.get(choice, MANUFACTURER_KEYS["1"])

    SERIAL_NUMBER = s_input
    CPE_PASSWORD = derive_cpe_password(acs_input, sk)
    print(f"[+] Using {vendor_name} key: {sk}")
    print(f"[+] Computed CPE Digest Password: {CPE_PASSWORD}")

SESSION_ID = "pc_tr069_session_01"

INFORM_XML = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:cwmp="urn:dslforum-org:cwmp-1-0">
  <soapenv:Header>
    <cwmp:ID soapenv:mustUnderstand="1">{SESSION_ID}</cwmp:ID>
  </soapenv:Header>
  <soapenv:Body>
    <cwmp:Inform>
      <DeviceId>
        <Manufacturer>Reliance Jio</Manufacturer>
        <OUI>000000</OUI>
        <ProductClass>{PRODUCT_CLASS}</ProductClass>
        <SerialNumber>{SERIAL_NUMBER}</SerialNumber>
      </DeviceId>
      <Event soapenv:arrayType="cwmp:EventStruct[1]">
        <EventStruct>
          <EventCode>1 BOOT</EventCode>
          <CommandKey></CommandKey>
        </EventStruct>
      </Event>
      <MaxEnvelopes>1</MaxEnvelopes>
      <CurrentTime>2026-11-14T12:00:00Z</CurrentTime>
      <RetryCount>0</RetryCount>
      <ParameterList soapenv:arrayType="cwmp:ParameterValueStruct[2]">
        <ParameterValueStruct>
          <Name>Device.DeviceInfo.SoftwareVersion</Name>
          <Value xsi:type="xsd:string" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">11.3.46</Value>
        </ParameterValueStruct>
        <ParameterValueStruct>
          <Name>Device.ManagementServer.ConnectionRequestURL</Name>
          <Value xsi:type="xsd:string" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">http://192.168.29.10:7547/tr069</Value>
        </ParameterValueStruct>
      </ParameterList>
    </cwmp:Inform>
  </soapenv:Body>
</soapenv:Envelope>"""

def main():
    print("=" * 60)
    print("  Jio STB Standalone ACS Query (TR-069 CWMP)")
    print(f"  Target:   {REAL_ACS_URL}")
    print(f"  Serial:   {SERIAL_NUMBER}")
    print(f"  Password: {CPE_PASSWORD}")
    print("=" * 60)

    session = requests.Session()
    session.verify = False
    session.auth = HTTPDigestAuth(SERIAL_NUMBER, CPE_PASSWORD)

    headers = {
        "Host": REAL_ACS_HOST,
        "User-Agent": "TR069-Client",
        "SOAPAction": "",
        "Content-Type": "text/xml; charset=utf-8",
        "Connection": "keep-alive"
    }

    try:
        print("[*] Sending CWMP Inform to Jio ACS...")
        resp = session.post(REAL_ACS_URL, data=INFORM_XML.encode("utf-8"), headers=headers, timeout=12)
        print(f"[+] HTTP Status: {resp.status_code}")
        print(f"[+] Response Headers:")
        for k, v in resp.headers.items():
            print(f"    {k}: {v}")

        if resp.status_code == 200:
            print("\n[+] Success! ACS Response Payload:")
            print(resp.text[:2000])
            
            # Send empty POST to continue TR-069 session handshake
            print("\n[*] Sending Empty POST to fetch server tasks...")
            empty_resp = session.post(REAL_ACS_URL, data="", headers=headers, timeout=12)
            print(f"[+] HTTP Status: {empty_resp.status_code}")
            if empty_resp.text:
                print("[+] ACS Task Payload:")
                print(empty_resp.text)
            else:
                print("[+] ACS returned empty body (no pending jobs).")
        elif resp.status_code == 204:
            print("[+] Status 204 No Content - Session accepted, no update pending for this build.")
        elif resp.status_code == 401:
            print("[-] HTTP 401 Unauthorized. Authentication failed. Check your Serial Number and ro.acsdata / secret key.")
        else:
            print(f"[!] Unexpected status {resp.status_code}:\n{resp.text}")

    except Exception as e:
        print(f"[-] Connection Error: {e}")
        print("\n[!] TROUBLESHOOTING:")
        print("    1. Jio's ACS (49.40.134.113:8443) is an internal Jio network endpoint.")
        print("       It is only reachable through an active JioFiber internet connection.")
        print("    2. If your PC is directly connected to the STB via an isolated Ethernet cable (192.168.50.1),")
        print("       your PC cannot route to 49.40.134.113.")
        print("    3. Remember: You DO NOT need this tool to unlock ADB! Run UNLOCK_ADB_ETHERNET.bat instead.")

if __name__ == "__main__":
    main()
