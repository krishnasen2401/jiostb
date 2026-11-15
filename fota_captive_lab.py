"""
Universal Jio STB Captive Lab Responder
Supports both Peer-to-Peer Ethernet (192.168.50.1) and Wi-Fi Mobile Hotspot (192.168.137.1).
Handles:
1. DNS Server (Port 53) -> Resolves acs.oss.jio.com and Google captive domains.
2. DHCP Server (Port 67) -> For Ethernet mode; hands out IP, DNS, Gateway.
3. HTTP Captive Server (Port 80) -> Returns forged AES-CBC FTTH Netcheck tokens.
4. HTTPS Transparent Relay (Port 443) -> Bridges STB to clients3.google.com:443.
"""

from pathlib import Path
import os
import sys
import socket
import socketserver
import struct
import threading
import time
import base64
import argparse

try:
    from Crypto.Cipher import AES
    _HAVE_AES = True
except Exception:
    _HAVE_AES = False

# AES Key for Jio FTTH Netcheck Token (/ftth/v1/network/check)
NETCHECK_KEY = b"6bm2I7pTdBaeABX0"
NETTYPE = "FTTH"
_PRECOMPUTED_NETCHECK = "UzLgdFHvJkBfRQiHnNQit+55dub3o1PbxIhuNZ7oJc8="

def _forge_netcheck():
    if not _HAVE_AES:
        return _PRECOMPUTED_NETCHECK
    try:
        iv = os.urandom(16)
        data = NETTYPE.encode()
        pl = 16 - (len(data) % 16)
        data += bytes([pl]) * pl
        ct = AES.new(NETCHECK_KEY, AES.MODE_CBC, iv).encrypt(data)
        return base64.b64encode(iv + ct).decode()
    except Exception:
        return _PRECOMPUTED_NETCHECK

BASE = Path(__file__).resolve().parent
PID_FILE = BASE / "fota-lab.pid"
DNS_LOG = BASE / "fota_dns_queries.log"
PORTAL_LOG = BASE / "fota_http_portal.log"

# Default configuration (Ethernet mode)
SERVICE_ADDRESS = "192.168.50.1"
SERVICE_BROADCAST_ADDRESS = "192.168.50.255"
CLIENT_ADDRESS = "192.168.50.2"
SUBNET_MASK = "255.255.255.0"
FAKE_ACS_IP = "49.44.112.10"
FAKE_GOOGLE_IP = "142.250.190.46"
ENABLE_DHCP = True

DNS_PORT = 53
DHCP_PORT = 67
_running = threading.Event()
_running.set()

def decode_name(packet, offset):
    labels = []
    cursor = offset
    next_offset = None
    visited = set()
    while True:
        if cursor >= len(packet) or cursor in visited:
            raise ValueError("invalid")
        visited.add(cursor)
        size = packet[cursor]
        if size & 0xC0 == 0xC0:
            if cursor + 1 >= len(packet):
                raise ValueError("truncated")
            pointer = ((size & 0x3F) << 8) | packet[cursor + 1]
            if next_offset is None:
                next_offset = cursor + 2
            cursor = pointer
            continue
        if size & 0xC0:
            raise ValueError("invalid")
        cursor += 1
        if size == 0:
            return ".".join(labels).lower(), (next_offset if next_offset is not None else cursor)
        labels.append(packet[cursor:cursor + size].decode("ascii", errors="strict"))
        cursor += size

def parse_question(packet):
    if len(packet) < 12:
        raise ValueError("short")
    name, after_name = decode_name(packet, 12)
    qtype, qclass = struct.unpack_from("!HH", packet, after_name)
    return name, qtype, qclass, after_name + 4

def local_dns_answer(query, client_ip):
    name, qtype, qclass, question_end = parse_question(query)
    query_id, request_flags = struct.unpack_from("!HH", query, 0)
    flags = 0x8400 | (request_flags & 0x0100)
    answer = b""
    answer_count = 0

    if qtype == 1 and qclass == 1:
        if "acs.oss.jio.com" in name:
            resolved = FAKE_ACS_IP
        elif "google" in name or "gstatic" in name:
            resolved = FAKE_GOOGLE_IP
        else:
            resolved = SERVICE_ADDRESS
        ip_bytes = socket.inet_aton(resolved)
        answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 30, len(ip_bytes)) + ip_bytes
        answer_count = 1
        msg = f"[DNS] {client_ip} queried: {name} -> resolved: {resolved}"
        print(msg, flush=True)
        try:
            with open(DNS_LOG, "a", encoding="utf-8") as lf:
                lf.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        except Exception:
            pass
    elif qtype == 28:
        msg = f"[DNS-AAAA] {client_ip} queried IPv6: {name} -> NODATA"
        print(msg, flush=True)
        try:
            with open(DNS_LOG, "a", encoding="utf-8") as lf:
                lf.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        except Exception:
            pass

    header = struct.pack("!HHHHHH", query_id, flags, 1, answer_count, 0, 0)
    return header + query[12:question_end] + answer

def udp_dns_loop(sock):
    while _running.is_set():
        try:
            data, addr = sock.recvfrom(2048)
            resp = local_dns_answer(data, addr[0])
            sock.sendto(resp, addr)
        except Exception:
            continue

def build_dhcp_reply(xid, chaddr, msg_type):
    op = 2
    htype = 1
    hlen = 6
    hops = 0
    secs = 0
    flags = 0x0000
    ciaddr = b"\x00\x00\x00\x00"
    yiaddr = socket.inet_aton(CLIENT_ADDRESS)
    siaddr = socket.inet_aton(SERVICE_ADDRESS)
    giaddr = b"\x00\x00\x00\x00"
    header = struct.pack("!BBBBIHH4s4s4s4s16s64s128s", op, htype, hlen, hops, xid, secs, flags, ciaddr, yiaddr, siaddr, giaddr, chaddr, b"", b"")
    magic = b"\x63\x82\x53\x63"
    options = bytearray()
    options.extend(b"\x35\x01" + bytes([msg_type]))
    options.extend(b"\x36\x04" + socket.inet_aton(SERVICE_ADDRESS))
    options.extend(b"\x33\x04" + struct.pack("!I", 86400))
    options.extend(b"\x01\x04" + socket.inet_aton(SUBNET_MASK))
    options.extend(b"\x03\x04" + socket.inet_aton(SERVICE_ADDRESS))
    options.extend(b"\x06\x04" + socket.inet_aton(SERVICE_ADDRESS))
    options.extend(b"\xff")
    return header + magic + bytes(options)

def dhcp_loop(sock):
    while _running.is_set():
        try:
            data, addr = sock.recvfrom(2048)
            if len(data) < 240:
                continue
            xid = struct.unpack("!I", data[4:8])[0]
            chaddr = data[28:44]
            # Check DHCP Message Type (Option 53)
            idx = 240
            msg_type = None
            while idx < len(data):
                opt = data[idx]
                if opt == 0xff: break
                if opt == 0x00: idx += 1; continue
                opt_len = data[idx+1]
                if opt == 0x35 and opt_len == 1:
                    msg_type = data[idx+2]
                    break
                idx += 2 + opt_len

            if msg_type == 1: # DISCOVER -> OFFER
                reply = build_dhcp_reply(xid, chaddr, 2)
                sock.sendto(reply, ("<broadcast>", 68))
                print(f"[DHCP] Sent OFFER to {CLIENT_ADDRESS}", flush=True)
            elif msg_type == 3: # REQUEST -> ACK
                reply = build_dhcp_reply(xid, chaddr, 5)
                sock.sendto(reply, ("<broadcast>", 68))
                print(f"[DHCP] Sent ACK to {CLIENT_ADDRESS}", flush=True)
        except Exception:
            continue

def handle_http_portal(conn, addr):
    try:
        raw = conn.recv(4096)
        if raw:
            req_line = raw.decode("latin1", errors="replace").split("\r\n")[0]
            if "/ftth/v1/network/check" in req_line:
                token = _forge_netcheck()
                body = f'{{"Network":"{token}"}}'.encode("utf-8")
                resp = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                    b"Connection: close\r\n\r\n" + body
                )
                conn.sendall(resp)
                msg = f"[PORTAL] {addr[0]} >>> {req_line} -> returned forged FTTH netcheck token"
            else:
                msg = f"[PORTAL] {addr[0]} >>> {req_line} -> returning HTTP 204"
                resp = b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                conn.sendall(resp)
            print(msg, flush=True)
            try:
                with open(PORTAL_LOG, "a", encoding="utf-8") as lf:
                    lf.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            except Exception:
                pass
    except Exception:
        pass
    finally:
        try: conn.close()
        except Exception: pass

def http_portal_loop():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(('0.0.0.0', 80))
        s.listen(10)
        s.settimeout(1.0)
        print("[PORTAL] HTTP 204 & Netcheck responder listening on port 80", flush=True)
        while _running.is_set():
            try:
                conn, addr = s.accept()
                threading.Thread(target=handle_http_portal, args=(conn, addr), daemon=True).start()
            except socket.timeout:
                continue
            except Exception:
                break
    except Exception as e:
        print(f"[PORTAL-ERR] Port 80 error: {e}", flush=True)
    finally:
        try: s.close()
        except Exception: pass

def pipe_sockets(s1, s2):
    try:
        while _running.is_set():
            data = s1.recv(4096)
            if not data: break
            s2.sendall(data)
    except Exception:
        pass
    finally:
        try: s1.close()
        except Exception: pass
        try: s2.close()
        except Exception: pass

def handle_https_tunnel(client_conn, addr):
    try:
        remote_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        remote_conn.settimeout(6.0)
        # Connect to real Google captive portal over PC's active Wi-Fi internet
        remote_conn.connect(("clients3.google.com", 443))
        remote_conn.settimeout(None)
        client_conn.settimeout(None)
        print(f"[HTTPS-TUNNEL] Relaying {addr[0]}:{addr[1]} -> clients3.google.com:443", flush=True)
        t1 = threading.Thread(target=pipe_sockets, args=(client_conn, remote_conn), daemon=True)
        t2 = threading.Thread(target=pipe_sockets, args=(remote_conn, client_conn), daemon=True)
        t1.start()
        t2.start()
    except Exception as e:
        try: client_conn.close()
        except Exception: pass

def https_tunnel_loop():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(('0.0.0.0', 443))
        s.listen(10)
        s.settimeout(1.0)
        print("[HTTPS-TUNNEL] Listening on port 443 (transparent relay to clients3.google.com)", flush=True)
        while _running.is_set():
            try:
                conn, addr = s.accept()
                threading.Thread(target=handle_https_tunnel, args=(conn, addr), daemon=True).start()
            except socket.timeout:
                continue
            except Exception:
                break
    except Exception as e:
        print(f"[HTTPS-TUNNEL-ERR] Port 443 error: {e}", flush=True)
    finally:
        try: s.close()
        except Exception: pass

def main():
    global SERVICE_ADDRESS, SERVICE_BROADCAST_ADDRESS, CLIENT_ADDRESS, ENABLE_DHCP
    parser = argparse.ArgumentParser(description="Jio STB Captive Lab Responder")
    parser.add_argument("--mode", choices=["ethernet", "wifi"], default="ethernet", help="Lab operating mode")
    args = parser.parse_args()

    if args.mode == "wifi":
        SERVICE_ADDRESS = "192.168.137.1"
        SERVICE_BROADCAST_ADDRESS = "192.168.137.255"
        CLIENT_ADDRESS = "192.168.137.19"
        ENABLE_DHCP = False # Windows Mobile Hotspot handles DHCP

    print("=" * 60)
    print("  JIO STB RESEARCH CAPTIVE LAB RESPONDER")
    print(f"  Mode:          {args.mode.upper()}")
    print(f"  Gateway & DNS: {SERVICE_ADDRESS}")
    print(f"  Fake ACS IP:   {FAKE_ACS_IP} (acs.oss.jio.com)")
    print(f"  DHCP Server:   {'Active (Port 67)' if ENABLE_DHCP else 'Disabled (handled by Hotspot)'}")
    print("=" * 60)

    try:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    # Start DNS UDP
    dns_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        dns_sock.bind(('0.0.0.0', DNS_PORT))
    except (PermissionError, OSError) as e:
        print(f"[!] Warning: Cannot bind 0.0.0.0:{DNS_PORT} ({e}). Retrying on {SERVICE_ADDRESS}:{DNS_PORT}...", flush=True)
        try:
            dns_sock.bind((SERVICE_ADDRESS, DNS_PORT))
            print(f"[+] Fallback successful: Bound UDP DNS directly to {SERVICE_ADDRESS}:{DNS_PORT}", flush=True)
        except (PermissionError, OSError) as e2:
            print(f"\n[ERROR] Port {DNS_PORT} (DNS) is blocked or in use by another process!", flush=True)
            print(f"        Common causes on Windows:", flush=True)
            print(f"        1. An orphaned python.exe process is still running. Run: taskkill /F /IM python.exe", flush=True)
            print(f"        2. Windows Mobile Hotspot / ICS DNS proxy. Run: Stop-Service SharedAccess -Force", flush=True)
            print(f"        3. Another DNS service or VPN is active (Docker, WSL2, AdGuard, etc.).\n", flush=True)
            sys.exit(1)
    threading.Thread(target=udp_dns_loop, args=(dns_sock,), daemon=True).start()
    print("[DNS] UDP DNS Server listening on port 53", flush=True)

    # Start DHCP (if Ethernet mode)
    if ENABLE_DHCP:
        dhcp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dhcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        dhcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            dhcp_sock.bind(('0.0.0.0', DHCP_PORT))
        except (PermissionError, OSError) as e:
            print(f"[!] Warning: Cannot bind 0.0.0.0:{DHCP_PORT} ({e}). Retrying on {SERVICE_ADDRESS}:{DHCP_PORT}...", flush=True)
            try:
                dhcp_sock.bind((SERVICE_ADDRESS, DHCP_PORT))
            except (PermissionError, OSError):
                print(f"[!] Warning: DHCP binding on {SERVICE_ADDRESS}:{DHCP_PORT} failed.", flush=True)
        threading.Thread(target=dhcp_loop, args=(dhcp_sock,), daemon=True).start()
        print("[DHCP] DHCP Server listening on port 67", flush=True)

    # Start HTTP Portal & Netcheck (Port 80)
    threading.Thread(target=http_portal_loop, daemon=True).start()

    # Start HTTPS Google Tunnel (Port 443)
    threading.Thread(target=https_tunnel_loop, daemon=True).start()

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping Captive Lab...")
        _running.clear()
        if PID_FILE.exists():
            PID_FILE.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
