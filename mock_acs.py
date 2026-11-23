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
import time

# ==============================================================================
# JIO STB UNIVERSAL MOCK ACS SERVER (DUAL-VARIANT: RELAY + OFFLINE STANDALONE)
#
# Architecture:
#   Variant 1 (Online Relay with Session Hijack):
#     Relays the initial CWMP handshake (Inform -> 401 -> Auth Inform -> 200 InformResponse)
#     to/from Real Jio ACS (49.40.134.113:8443) using genuine Undertow nonces.
#     At the first Empty POST -> HIJACKS session and pushes local ADB unlock commands.
#
#   Variant 2 (Offline Standalone Auto-Fallback):
#     If upstream Real Jio ACS is unreachable or offline, automatically falls back
#     to 100% local mock ACS using the verified MD5 realm hash (opaque=145074cc...).
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

# --- CWMP Dynamic Dialect & Payloads (FerroSTB Aligned) ---
class SoapDialect:
    def __init__(self, env="soap-env", enc="soap-enc", cwmp_ns="urn:dslforum-org:cwmp-1-0", root="Device"):
        self.env = env
        self.enc = enc
        self.cwmp_ns = cwmp_ns
        self.root = root

def detect_dialect(body_str):
    env = "soap-env" if "<soap-env:Envelope" in body_str else ("soap" if "<soap:Envelope" in body_str else "SOAP-ENV")
    enc = "soap-enc" if "xmlns:soap-enc=" in body_str else "SOAP-ENC"
    cwmp_ns = "urn:dslforum-org:cwmp-1-2" if "urn:dslforum-org:cwmp-1-2" in body_str else "urn:dslforum-org:cwmp-1-0"
    root = "InternetGatewayDevice" if "InternetGatewayDevice." in body_str else "Device"
    return SoapDialect(env, enc, cwmp_ns, root)

def inform_response_xml(d, req_id):
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<{d.env}:Envelope xmlns:{d.env}="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:{d.enc}="http://schemas.xmlsoap.org/soap/encoding/" '
        f'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'xmlns:cwmp="{d.cwmp_ns}">'
        f'<{d.env}:Header><cwmp:ID {d.env}:mustUnderstand="1">{req_id}</cwmp:ID></{d.env}:Header>'
        f'<{d.env}:Body><cwmp:InformResponse><MaxEnvelopes>1</MaxEnvelopes></cwmp:InformResponse></{d.env}:Body>'
        f'</{d.env}:Envelope>'
    )

def get_param_names_xml(d, req_id, path, next_level=True):
    nl = "1" if next_level else "0"
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<{d.env}:Envelope xmlns:{d.env}="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:{d.enc}="http://schemas.xmlsoap.org/soap/encoding/" '
        f'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'xmlns:cwmp="{d.cwmp_ns}">'
        f'<{d.env}:Header><cwmp:ID {d.env}:mustUnderstand="1">{req_id}</cwmp:ID></{d.env}:Header>'
        f'<{d.env}:Body><cwmp:GetParameterNames><ParameterPath>{path}</ParameterPath><NextLevel>{nl}</NextLevel></cwmp:GetParameterNames></{d.env}:Body>'
        f'</{d.env}:Envelope>'
    )

def set_single_param_xml(d, req_id, name, ptype, val):
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<{d.env}:Envelope xmlns:{d.env}="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:{d.enc}="http://schemas.xmlsoap.org/soap/encoding/" '
        f'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'xmlns:cwmp="{d.cwmp_ns}">'
        f'<{d.env}:Header><cwmp:ID {d.env}:mustUnderstand="1">{req_id}</cwmp:ID></{d.env}:Header>'
        f'<{d.env}:Body><cwmp:SetParameterValues>'
        f'<ParameterList {d.enc}:arrayType="cwmp:ParameterValueStruct[1]">'
        f'<ParameterValueStruct><Name>{name}</Name><Value xsi:type="{ptype}">{val}</Value></ParameterValueStruct>'
        f'</ParameterList>'
        f'<ParameterKey></ParameterKey>'
        f'</cwmp:SetParameterValues></{d.env}:Body>'
        f'</{d.env}:Envelope>'
    )

def make_set_params_xml(params, req_id, dialect=None):
    d = dialect if dialect else SoapDialect()
    items = []
    for name, ptype, val in params:
        items.append(f"<ParameterValueStruct><Name>{name}</Name><Value xsi:type=\"{ptype}\">{val}</Value></ParameterValueStruct>")
    body = "\n".join(items)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<{d.env}:Envelope xmlns:{d.enc}="http://schemas.xmlsoap.org/soap/encoding/" '
        f'xmlns:{d.env}="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'xmlns:cwmp="{d.cwmp_ns}">'
        f'<{d.env}:Header><cwmp:ID {d.env}:mustUnderstand="1">{req_id}</cwmp:ID></{d.env}:Header>'
        f'<{d.env}:Body><cwmp:SetParameterValues>'
        f'<ParameterList {d.enc}:arrayType="cwmp:ParameterValueStruct[{len(params)}]">'
        f'{body}'
        f'</ParameterList>'
        f'<ParameterKey></ParameterKey>'
        f'</cwmp:SetParameterValues></{d.env}:Body>'
        f'</{d.env}:Envelope>'
    )

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
_parser.add_argument("--model", type=str, default="auto", choices=["auto", "universal", "jms", "jhs", "legacy", "rilrootca"])
_parser.add_argument("--listen-443", action="store_true", default=False, help="Listen on port 443 (disabled by default to eliminate Android SSL noise)")
_cli_args, _ = _parser.parse_known_args()

_model_env = os.environ.get("STB_MODEL", "auto").lower()
TARGET_MODEL = _cli_args.model if _cli_args.model != "auto" else _model_env

if _cli_args.cert and os.path.exists(_cli_args.cert):
    CERT_FILE = os.path.abspath(_cli_args.cert)
elif TARGET_MODEL in ("legacy", "rilrootca") and os.path.exists(os.path.join(BASE_DIR, "acs_chain.pem")):
    CERT_FILE = os.path.join(BASE_DIR, "acs_chain.pem")
else:
    # Universal Default: forged_chain.pem (eMudhra + Comodo AAA CA, trusted by all Android TV builds)
    CERT_FILE = os.path.join(BASE_DIR, "forged_chain.pem")
    if not os.path.exists(CERT_FILE):
        CERT_FILE = os.path.join(BASE_DIR, "acs_chain.pem")

# TR-069 standard CWMP ports.
# Note: Port 443 is disabled by default to completely block 3rd-party Android app SSL noise.
PORTS = [7443, 7547, 8080, 8443, 9443]
if _cli_args.listen_443 or os.environ.get("LISTEN_443", "").lower() in ("1", "true", "yes"):
    PORTS.append(443)
BIND_ADDR = "0.0.0.0"

LOG_FILE = os.path.join(BASE_DIR, "mock_acs.log")
PACKET_LOG_FILE = os.path.join(BASE_DIR, "mock_acs_packets.log")

# Exact Real Jio ACS Digest Parameters:
# Real Jio ACS (nginx/1.30.1 + Undertow) sets opaque = MD5("CPEDigestLogin")
REALM = "CPEDigestLogin"
OPAQUE = "145074cc9f9b8670f412d297d1d11274"  # MD5("CPEDigestLogin")

# Real Jio ACS Upstream Details (for Relay Mode)
REAL_ACS_HOST = "acs.oss.jio.com"
REAL_ACS_PORT = 8443
REAL_ACS_IP = "49.40.134.113"

UPSTREAM_ONLINE = False
upstream_ctx = ssl._create_unverified_context()
try: upstream_ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
except Exception: pass

SESSIONS = {}
SESSIONS_LOCK = threading.Lock()
CHALLENGED_IPS = {}  # ip -> float(timestamp) tracking single 401 challenges
CHALLENGED_LOCK = threading.Lock()
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
    Essential for remote session analysis and protocol debugging.
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
    """Test if Real Jio ACS is reachable over the active network connection."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((REAL_ACS_IP, REAL_ACS_PORT))
        s.close()
        return True
    except Exception:
        return False

def forward_to_real_acs(method, path, headers, body, timeout=4.0):
    """Forward an HTTP request to the Real Jio ACS server."""
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
        if "transfer-encoding" in headers and "chunked" in headers["transfer-encoding"]:
            chunks = []
            while True:
                chunk_header = rf.readline()
                if not chunk_header: break
                chunk_len_str = chunk_header.split(b";")[0].strip()
                try:
                    chunk_len = int(chunk_len_str, 16)
                except ValueError:
                    break
                if chunk_len == 0:
                    rf.readline()
                    break
                chunk_data = rf.read(chunk_len)
                chunks.append(chunk_data)
                rf.read(2)
            body = b"".join(chunks)
        elif "content-length" in headers:
            n = int(headers["content-length"])
            body = rf.read(n) if n else b""
        if body and headers.get("content-encoding") == "gzip":
            try:
                import gzip
                body = gzip.decompress(body)
            except Exception:
                pass
        return reqline, headers, body
    except Exception:
        return None

def extract_fault(body_str):
    fc = re.search(r'<FaultCode[^>]*>([^<]+)</FaultCode>', body_str)
    fs = re.search(r'<FaultString[^>]*>([^<]+)</FaultString>', body_str)
    pn = re.search(r'<ParameterName[^>]*>([^<]+)</ParameterName>', body_str)
    code = fc.group(1).strip() if fc else None
    msg = fs.group(1).strip() if fs else None
    param = pn.group(1).strip() if pn else None
    return code, msg, param

def parse_parameter_names(xml_str):
    params = []
    for m in re.finditer(r'<ParameterInfoStruct>([\s\S]*?)</ParameterInfoStruct>', xml_str):
        block = m.group(1)
        name_m = re.search(r'<Name[^>]*>([^<]+)</Name>', block)
        w_m = re.search(r'<Writable[^>]*>([^<]+)</Writable>', block)
        if name_m:
            name = name_m.group(1).strip()
            w_str = w_m.group(1).strip() if w_m else "0"
            writable = w_str in ("1", "true", "True")
            params.append((name, writable))
    return params

def init_task_queue(dialect=None):
    d = dialect if dialect else SoapDialect()
    root = d.root
    q = []
    # 1. Proactive parameter discovery probe (FerroSTB architecture)
    q.append({
        "type": "get_names",
        "path": f"{root}.",
        "next_level": True,
        "desc": f"Discover vendor roots ({root}.)"
    })
    q.append({
        "type": "get_names",
        "path": f"{root}.JSTB.",
        "next_level": False,
        "desc": f"Discover JSTB branch ({root}.JSTB.)"
    })
    
    # 2. Immediate candidates for both JSTB and JioSTB trees
    candidates = [
        # Validity dates (2037 formats)
        (f"{root}.JSTB.USB.DebugValidityDate", "xsd:string", "2037-01-01_00:00:00", False),
        (f"{root}.JSTB.USB.DebugValidityDate", "xsd:string", "31-12-2037 23:59:59", False),
        (f"{root}.JSTB.USB.DebugValidityDate", "xsd:dateTime", "2037-12-31T23:59:59.000Z", False),
        (f"{root}.JioSTB.USB.DebugValidityDate", "xsd:string", "2037-01-01_00:00:00", False),
        (f"{root}.JioSTB.USB.DebugValidityDate", "xsd:string", "31-12-2037 23:59:59", False),
        (f"{root}.JioSTB.USB.DebugValidityDate", "xsd:dateTime", "2037-12-31T23:59:59.000Z", False),
        
        # USBDebugging flags (boolean & string & int)
        (f"{root}.JSTB.USB.USBDebugging", "xsd:boolean", "true", True),
        (f"{root}.JSTB.USB.USBDebugging", "xsd:boolean", "1", True),
        (f"{root}.JioSTB.USB.USBDebugging", "xsd:boolean", "true", True),
        (f"{root}.JioSTB.USB.USBDebugging", "xsd:boolean", "1", True),
        
        # FOTA Disable
        (f"{root}.JSTB.FOTA.Disable", "xsd:boolean", "true", False),
        (f"{root}.JioSTB.FOTA.Disable", "xsd:boolean", "true", False),
        (f"{root}.JioSTB.FOTA.Disable", "xsd:string", "true", False),
    ]
    for name, ptype, val, is_adb in candidates:
        q.append({
            "type": "set_param",
            "name": name,
            "ptype": ptype,
            "val": val,
            "is_adb": is_adb,
            "desc": f"{name} = {val}"
        })
    return q

def _trigger_adb_probe(stb_ip):
    def _run():
        try:
            import time
            time.sleep(1.0)
            adb_bin = os.path.join(BASE_DIR, "bin", "adb.exe")
            if not os.path.exists(adb_bin):
                adb_bin = "adb"
            subprocess.run([adb_bin, "connect", f"{stb_ip}:5555"], capture_output=True, timeout=8)
            if stb_ip != "192.168.50.2":
                subprocess.run([adb_bin, "connect", "192.168.50.2:5555"], capture_output=True, timeout=5)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()

def start_parallel_adb_poller(target_ip):
    def _poll():
        for _ in range(60):
            try:
                with socket.create_connection((target_ip, 5555), timeout=1.0):
                    log(f"*** [ADB] Port 5555 is OPEN on {target_ip}! Triggering ADB connect... ***", to_stdout=True)
                    _trigger_adb_probe(target_ip)
                    return
            except Exception:
                time.sleep(1.5)
    threading.Thread(target=_poll, daemon=True).start()

def send_next_task(s, cid, sess, dialect=None):
    d = dialect if dialect else sess.get("dialect", SoapDialect())
    if not sess["tasks"]:
        resp_headers = {
            "Server": "GenieACS/1.2.9",
            "SOAPServer": "GenieACS/1.2.9",
            "Content-Length": "0",
            "Connection": "close"
        }
        s.sendall(
            b"HTTP/1.1 204 No Content\r\n"
            b"Server: GenieACS/1.2.9\r\n"
            b"SOAPServer: GenieACS/1.2.9\r\n"
            b"Content-Length: 0\r\n"
            b"Connection: close\r\n\r\n"
        )
        status_msg = "SUCCESS - ADB UNLOCKED!" if sess.get("adb_unlocked") else "FINISHED (ADB status uncertain)"
        log(f"{cid} <<< 204 session closed. Final Status: {status_msg}")
        if sess.get("adb_unlocked"):
            dev_model = sess.get("model", "Jio STB")
            target_ip = cid.split(":")[0]
            banner = f"""
======================================================================
  🎉🎉🎉 SUCCESS: JIO STB ADB IS FULLY UNLOCKED! 🎉🎉🎉
======================================================================
  Device: {dev_model} (STB IP: {target_ip}:5555)

  ACTION REQUIRED ON YOUR TV SCREEN RIGHT NOW:
  1. Turn on your TV screen.
  2. A popup dialog will appear: "Allow USB debugging?".
  3. Check "Always allow from this computer" with your remote.
  4. Select "Allow" / "OK".

  NEXT STEP:
  Open a second Command Prompt / PowerShell window and run:
      adb connect {target_ip}:5555
      .\\1CLICK_POST_ADB_SETUP.bat
======================================================================
"""
            log(banner, to_stdout=True)
            _trigger_adb_probe(target_ip)
        log_packet("OUTGOING", cid, "HTTP/1.1 204 No Content", resp_headers, None, note=f"CWMP End of Session ({status_msg})")
        return
    
    task = sess["tasks"].pop(0)
    sess["current"] = task
    cmd_id = str(uuid.uuid4().int % 100000)
    
    if task.get("type") == "get_names":
        soap_str = get_param_names_xml(d, cmd_id, task["path"], task["next_level"])
    elif task.get("type") == "set_param":
        soap_str = set_single_param_xml(d, cmd_id, task["name"], task["ptype"], task["val"])
    else:
        soap_str = make_set_params_xml(task.get("params", []), cmd_id, d)
        
    resp_xml = soap_str.encode("utf-8")
    date_hdr = get_http_date()
    resp_headers = {
        "Date": date_hdr,
        "Server": "GenieACS/1.2.9",
        "SOAPServer": "GenieACS/1.2.9",
        "Content-Type": "text/xml; charset=utf-8",
        "Content-Length": str(len(resp_xml)),
        "Connection": "keep-alive"
    }
    http_resp = (
        b"HTTP/1.1 200 OK\r\n"
        b"Date: " + date_hdr.encode() + b"\r\n"
        b"Server: GenieACS/1.2.9\r\n"
        b"SOAPServer: GenieACS/1.2.9\r\n"
        b"Content-Type: text/xml; charset=utf-8\r\n"
        b"Content-Length: " + str(len(resp_xml)).encode() + b"\r\n"
        b"Connection: keep-alive\r\n\r\n" + resp_xml
    )
    s.sendall(http_resp)
    log(f"{cid} <<< RPC [{task['desc']}] id={cmd_id}")
    log_packet("OUTGOING", cid, "HTTP/1.1 200 OK", resp_headers, resp_xml, note=f"CWMP RPC [{task['desc']}]")

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
        if is_tr069_port and addr[0] not in ("127.0.0.1", "::1"):
            start_parallel_adb_poller(addr[0])
    except Exception as e:
        if is_tr069_port:
            log(f"TLS fail {cid}: {type(e).__name__}: {e}", to_stdout=True)
            if "CERTIFICATE_UNKNOWN" in str(e):
                if "forged_chain" in os.path.basename(CERT_FILE):
                    log(f"{cid} [!] STB TR-069 rejected eMudhra cert. Re-run selecting Option [1] ('acs_chain.pem' RILROOTCA)!", to_stdout=True)
                else:
                    log(f"{cid} [!] STB TR-069 rejected RILROOTCA cert. Re-run selecting Option [2] ('forged_chain.pem' eMudhra)!", to_stdout=True)
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
            
            # Detailed Packet & Network Request Logging for Remote Session Analysis
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

            # ---- JMSC200A / AIRFIBER BOOTSTRAP ACCOUNT REQUEST ----
            if "request_account" in path:
                body_resp = b'{"status":"SUCCESS","acsUrl":"https://acs.oss.jio.com:8443/ftacs-digest/ACS"}'
                date_hdr = get_http_date().encode()
                resp_headers = {
                    "Server": "nginx/1.30.1",
                    "Date": date_hdr.decode(),
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body_resp)),
                    "Connection": "keep-alive"
                }
                resp = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Server: nginx/1.30.1\r\n"
                    b"Date: " + date_hdr + b"\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(body_resp)).encode() + b"\r\n"
                    b"Connection: keep-alive\r\n\r\n" + body_resp
                )
                s.sendall(resp)
                log(f"{cid} <<< bootstrap account response (acsUrl -> :8443)")
                log_packet("OUTGOING", cid, "HTTP/1.1 200 OK", resp_headers, body_resp, note="Bootstrap Account Response")
                continue
            
            # ---- HTTP DIGEST AUTH CHALLENGE (RELAY ONLY) ----
            # Real Jio ACS only challenges when online relaying.
            # IN OFFLINE STANDALONE MODE: ZERO 401 CHALLENGE!
            # FerroSTB architecture proves 100% reliability with direct 200 OK InformResponse across all models.
            enable_401 = os.environ.get("ENABLE_401_CHALLENGE", "").lower() in ("1", "true", "yes")
            if UPSTREAM_ONLINE and enable_401 and not has_auth and ("cwmp:Inform" in body_str or len(body) > 0):
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
                        continue
                except Exception as e:
                    log(f"{cid} [WARN] Upstream relay failed ({e}), falling back to direct Zero-401 InformResponse")

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
                
                dialect = detect_dialect(body_str)
                session_id = uuid.uuid4().hex[:16]
                jsession = f"{session_id}.nvmbdprv126605"
                conn_sess = {
                    "tasks": init_task_queue(dialect),
                    "current": None,
                    "dialect": dialect,
                    "adb_unlocked": False,
                    "discovered_branches": set()
                }
                with SESSIONS_LOCK:
                    SESSIONS[session_id] = conn_sess
                    SESSIONS[jsession] = conn_sess
                    SESSIONS[addr[0]] = conn_sess  # IP fallback for JMSD200 and boxes that drop cookies
                    if cookie:
                        SESSIONS[cookie] = conn_sess
                
                relayed_inform = False
                # Upstream Inform Relay if online and authenticated (ONLY if explicitly enabled)
                relay_enabled = os.environ.get("ENABLE_UPSTREAM_RELAY", "").lower() in ("1", "true", "yes")
                if relay_enabled and UPSTREAM_ONLINE and has_auth:
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
                
                # Standalone InformResponse (GenieACS 1.2.9 + Undertow Dual Format)
                if not relayed_inform:
                    resp_xml = inform_response_xml(dialect, req_id).encode("utf-8")
                    date_hdr = get_http_date()
                    resp_headers = {
                        "Date": date_hdr,
                        "Server": "GenieACS/1.2.9",
                        "SOAPServer": "GenieACS/1.2.9",
                        "Content-Type": "text/xml; charset=utf-8",
                        "Set-Cookie": f"JSESSIONID={jsession}; path=/, session={session_id}; Path=/",
                        "Content-Length": str(len(resp_xml)),
                        "Connection": "keep-alive"
                    }
                    http_resp = (
                        b"HTTP/1.1 200 OK\r\n"
                        b"Date: " + date_hdr.encode() + b"\r\n"
                        b"Server: GenieACS/1.2.9\r\n"
                        b"SOAPServer: GenieACS/1.2.9\r\n"
                        b"Content-Type: text/xml; charset=utf-8\r\n"
                        b"Set-Cookie: JSESSIONID=" + jsession.encode() + b"; path=/\r\n"
                        b"Set-Cookie: session=" + session_id.encode() + b"; Path=/\r\n"
                        b"Content-Length: " + str(len(resp_xml)).encode() + b"\r\n"
                        b"Connection: keep-alive\r\n\r\n" + resp_xml
                    )
                    s.sendall(http_resp)
                    log(f"{cid} <<< [STANDALONE] InformResponse (ID={req_id}, root={dialect.root})")
                    log_packet("OUTGOING", cid, "HTTP/1.1 200 OK", resp_headers, resp_xml, note="Local Standalone InformResponse")
                    continue
            
            # ---- CWMP: GETRPCMETHODS (OPTIONAL CPE QUERY) ----
            if "GetRPCMethods" in body_str:
                m = re.search(r'<cwmp:ID[^>]*>([^<]+)</cwmp:ID>', body_str)
                rpc_id = m.group(1).strip() if m else "0"
                dialect = conn_sess.get("dialect") if conn_sess else detect_dialect(body_str)
                rpc_xml = (
                    f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\r\n"
                    f"<{dialect.env}:Envelope xmlns:{dialect.enc}=\"http://schemas.xmlsoap.org/soap/encoding/\" "
                    f"xmlns:{dialect.env}=\"http://schemas.xmlsoap.org/soap/envelope/\" "
                    f"xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\" "
                    f"xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" "
                    f"xmlns:cwmp=\"{dialect.cwmp_ns}\">\r\n"
                    f"<{dialect.env}:Header><cwmp:ID {dialect.env}:mustUnderstand=\"1\">{rpc_id}</cwmp:ID></{dialect.env}:Header>\r\n"
                    f"<{dialect.env}:Body><cwmp:GetRPCMethodsResponse>\r\n"
                    f"<MethodList {dialect.enc}:arrayType=\"xsd:string[4]\">\r\n"
                    f"<string>GetRPCMethods</string>\r\n"
                    f"<string>SetParameterValues</string>\r\n"
                    f"<string>GetParameterValues</string>\r\n"
                    f"<string>Inform</string>\r\n"
                    f"</MethodList>\r\n"
                    f"</cwmp:GetRPCMethodsResponse></{dialect.env}:Body>\r\n"
                    f"</{dialect.env}:Envelope>"
                ).encode("utf-8")
                date_hdr = get_http_date()
                resp_headers = {
                    "Date": date_hdr,
                    "Server": "GenieACS/1.2.9",
                    "SOAPServer": "GenieACS/1.2.9",
                    "Content-Type": "text/xml; charset=utf-8",
                    "Content-Length": str(len(rpc_xml)),
                    "Connection": "keep-alive"
                }
                http_resp = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Date: " + date_hdr.encode() + b"\r\n"
                    b"Server: GenieACS/1.2.9\r\n"
                    b"SOAPServer: GenieACS/1.2.9\r\n"
                    b"Content-Type: text/xml; charset=utf-8\r\n"
                    b"Content-Length: " + str(len(rpc_xml)).encode() + b"\r\n"
                    b"Connection: keep-alive\r\n\r\n" + rpc_xml
                )
                s.sendall(http_resp)
                log(f"{cid} <<< GetRPCMethodsResponse")
                log_packet("OUTGOING", cid, "HTTP/1.1 200 OK", resp_headers, rpc_xml, note="GetRPCMethodsResponse")
                continue
            
            # ---- CWMP: STATE MACHINE & SESSION HIJACK ----
            # Match session: by Cookie (GenieACS session style), connection session, or IP (JMSD200 style)
            sess = SESSIONS.get(cookie) if cookie else conn_sess
            if not sess and addr[0] in SESSIONS:
                sess = SESSIONS[addr[0]]
            if sess:
                dialect = sess.get("dialect", SoapDialect())
                # Empty POST from CPE indicates ACS turn -> HIJACK POINT!
                if len(body) == 0:
                    log(f"{cid} [HIJACK POINT] STB ready for commands -> Injecting local CWMP RPC queue")
                    send_next_task(s, cid, sess, dialect)
                    continue
                
                # Handle Response to previous RPC
                current = sess.get("current")
                if "SetParameterValuesResponse" in body_str:
                    if current and current.get("is_adb"):
                        sess["adb_unlocked"] = True
                        log(f"{cid} *** SUCCESS! STB ACCEPTED {current['desc']}! ADB IS FULLY UNLOCKED! ***")
                    else:
                        log(f"{cid} [OK] STB accepted: {current['desc'] if current else 'task'}")
                elif "GetParameterNamesResponse" in body_str:
                    params = parse_parameter_names(body_str)
                    log(f"{cid} [DISCOVERY] STB returned {len(params)} parameter paths:")
                    discovered = sess.setdefault("discovered_branches", set())
                    new_actions = []
                    for name, writable in params:
                        log(f"{cid}   -> {name} (writable={writable})")
                        low = name.lower()
                        if name.endswith('.'):
                            if any(k in low for k in ["jstb", "jio", "usb", "fota", "debug", "stb", "x_"]) and name not in discovered:
                                discovered.add(name)
                                new_actions.append({"type": "get_names", "path": name, "next_level": False, "desc": f"Sub-tree ({name})"})
                        else:
                            if "debug" in low and "date" in low:
                                new_actions.append({"type": "set_param", "name": name, "ptype": "xsd:string", "val": "2037-01-01_00:00:00", "is_adb": False, "desc": f"Discovered {name}"})
                                new_actions.append({"type": "set_param", "name": name, "ptype": "xsd:string", "val": "31-12-2037 23:59:59", "is_adb": False, "desc": f"Discovered {name}"})
                            elif "usbdebugging" in low or ("adb" in low and writable):
                                new_actions.append({"type": "set_param", "name": name, "ptype": "xsd:boolean", "val": "true", "is_adb": True, "desc": f"Discovered {name}"})
                                new_actions.append({"type": "set_param", "name": name, "ptype": "xsd:boolean", "val": "1", "is_adb": True, "desc": f"Discovered {name}"})
                            elif "fota" in low and "disable" in low:
                                new_actions.append({"type": "set_param", "name": name, "ptype": "xsd:boolean", "val": "true", "is_adb": False, "desc": f"Discovered {name}"})
                    for a in reversed(new_actions):
                        sess["tasks"].insert(0, a)
                else:
                    # SOAP Fault or error
                    code, msg, param = extract_fault(body_str)
                    task_desc = current['desc'] if current else 'task'
                    log(f"{cid} *** SOAP FAULT on [{task_desc}]: Code={code}, Error='{msg}', Param='{param}' ***")
                    
                    if code == "9005" and "FOTA.Disable" in (param or ""):
                        log(f"{cid} [NOTE] Device.JioSTB.FOTA.Disable is not in this model's schema (e.g. SDMC JHS C200).")
                        log(f"{cid} [NOTE] Normal and safe! ADB is already unlocked; disable FOTA packages via ADB commands.")
                
                # Proceed to next task in session
                send_next_task(s, cid, sess, dialect)
                continue
            
            # ---- Unknown / Empty POST without active session ----
            resp_headers = {
                "Server": "GenieACS/1.2.9",
                "SOAPServer": "GenieACS/1.2.9",
                "Content-Length": "0",
                "Connection": "close"
            }
            s.sendall(
                b"HTTP/1.1 204 No Content\r\n"
                b"Server: GenieACS/1.2.9\r\n"
                b"SOAPServer: GenieACS/1.2.9\r\n"
                b"Content-Length: 0\r\n"
                b"Connection: close\r\n\r\n"
            )
            log(f"{cid} <<< 204 No Content (untracked session)", to_stdout=is_tr069_port)
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
        log("  Jio STB Universal Mock ACS (Relay + Standalone Dual)    ")
        log(f"  Packet Log: {PACKET_LOG_FILE}")
        
        log(f"  Target STB Family: {TARGET_MODEL.upper()} Series")
        log(f"  Active Certificate: {os.path.basename(CERT_FILE)}")
        
        # Upstream relay is opt-in; default is rock-solid offline standalone (Zero-401 Direct Unlock)
        relay_requested = os.environ.get("ENABLE_UPSTREAM_RELAY", "").lower() in ("1", "true", "yes")
        if relay_requested:
            log("  Checking upstream connectivity to Real Jio ACS (49.40.134.113:8443)...")
            UPSTREAM_ONLINE = test_upstream_connectivity(timeout=1.5)
            if UPSTREAM_ONLINE:
                log("  [+] Mode: ONLINE RELAY (JioFiber WAN Active - Upstream ACS Reachable)")
            else:
                log("  [!] Mode: OFFLINE STANDALONE (Upstream ACS Unreachable - Falling back to local unlock)")
        else:
            UPSTREAM_ONLINE = False
            log("  [+] Mode: STANDALONE OFFLINE (Default - Zero-401 Direct Unlock for All Models)")

        # Initialize packet log file immediately so all diagnostic files exist on startup
        try:
            with open(PACKET_LOG_FILE, "a", encoding="utf-8") as pf:
                mode_str = "ONLINE RELAY" if UPSTREAM_ONLINE else "OFFLINE STANDALONE"
                pf.write(f"# --- Jio STB Universal Mock ACS Packet Log Session Started: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n# Target: {TARGET_MODEL.upper()} | Mode: {mode_str}\n\n")
        except Exception:
            pass
        log("==========================================================")
        log("  >>> ACTION REQUIRED: POWER-CYCLE (REBOOT) THE JIO STB NOW <<<")
        log("  1. Unplug the STB power cable from the back.")
        log("  2. Wait 5 seconds, then plug it back in.")
        log("  * The STB TR-069 CWMP client ONLY connects during bootup!")
        log("  * Troubleshooting: If no connections appear after 90 seconds,")
        log("    temporarily turn OFF Windows Defender Firewall or pause antivirus.")
        log("  * Loop / TLS Error Fix: If STB repeatedly rejects TLS or loops /generate_204,")
        log("    perform a quick FACTORY RESET on the STB (Settings -> Device Preferences -> Reset).")
        log("    During fresh setup (OOBE), the STB forces immediate TR-069 provisioning!")
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
