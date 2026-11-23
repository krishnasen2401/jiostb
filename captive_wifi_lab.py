import base64
from pathlib import Path
import os
import sys
import socket
import socketserver
import struct
import threading
import time

try:
    from Crypto.Cipher import AES
    _HAVE_AES = True
except Exception:
    _HAVE_AES = False

NETCHECK_KEY = b"6bm2I7pTdBaeABX0"
_PRECOMPUTED_NETCHECK = "UzLgdFHvJkBfRQiHnNQit+55dub3o1PbxIhuNZ7oJc8="

def _forge_netcheck():
    if not _HAVE_AES:
        return _PRECOMPUTED_NETCHECK
    try:
        iv = os.urandom(16)
        data = b"FTTH"
        pl = 16 - (len(data) % 16)
        data += bytes([pl]) * pl
        ct = AES.new(NETCHECK_KEY, AES.MODE_CBC, iv).encrypt(data)
        return base64.b64encode(iv + ct).decode()
    except Exception:
        return _PRECOMPUTED_NETCHECK

BASE = Path(__file__).resolve().parent
PID_FILE = BASE / "captive-wifi-lab.pid"
SERVICE_ADDRESS = "192.168.137.1"
SERVICE_BROADCAST_ADDRESS = "192.168.137.255"
FAKE_ACS_IP = "49.44.112.10"
FAKE_GOOGLE_IP = "142.250.190.46"
DNS_PORT = 53
DHCP_PORT = 67
CLIENT_ADDRESS = "192.168.137.19"
SUBNET_MASK = "255.255.255.0"
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
            # Single Direct DNS Answer: route directly to PC service IP (192.168.137.1)
            # Avoids duplicate simultaneous TCP sockets and CWMP session race conditions
            resolved = SERVICE_ADDRESS
            ip_bytes = socket.inet_aton(resolved)
            answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 30, len(ip_bytes)) + ip_bytes
            answer_count = 1
            msg = f"[DNS] {client_ip} queried: {name} -> resolved: {resolved}"
            print(msg, flush=True)
            try:
                with open(BASE / "captive_wifi_lab.log", "a", encoding="utf-8") as lf:
                    lf.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            except Exception:
                pass
            header = struct.pack("!HHHHHH", query_id, flags, 1, answer_count, 0, 0)
            return header + query[12:question_end] + answer
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
            with open(BASE / "captive_wifi_lab.log", "a", encoding="utf-8") as lf:
                lf.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        except Exception:
            pass
    elif qtype == 28:
        msg = f"[DNS-AAAA] {client_ip} queried IPv6: {name} -> NODATA"
        print(msg, flush=True)
        try:
            with open(BASE / "captive_wifi_lab.log", "a", encoding="utf-8") as lf:
                lf.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        except Exception:
            pass
        
    header = struct.pack("!HHHHHH", query_id, flags, 1, answer_count, 0, 0)
    return header + query[12:question_end] + answer

def recv_exact(sock, length):
    data = bytearray()
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("closed")
        data.extend(chunk)
    return bytes(data)

class DnsTcpHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            size = struct.unpack("!H", recv_exact(self.request, 2))[0]
            query = recv_exact(self.request, size)
            answer = local_dns_answer(query, self.client_address[0])
            self.request.sendall(struct.pack("!H", len(answer)) + answer)
        except Exception:
            return

class ThreadedDnsTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

def udp_dns_loop(sock):
    while _running.is_set():
        try:
            query, peer = sock.recvfrom(4096)
            answer = local_dns_answer(query, peer[0])
            sock.sendto(answer, peer)
        except Exception as e:
            try:
                print(f"[DNS-ERR] Error handling query from {peer[0]}: {e}", flush=True)
            except Exception:
                pass
            continue

def parse_dhcp_options(packet):
    options = {}
    offset = 240
    while offset < len(packet):
        code = packet[offset]
        offset += 1
        if code == 255:
            break
        if code == 0:
            continue
        size = packet[offset]
        offset += 1
        options[code] = packet[offset:offset + size]
        offset += size
    return options

def dhcp_option(code, value):
    return bytes((code, len(value))) + value

def make_dhcp_reply(request, message_type):
    if len(request) < 240 or request[236:240] != b"\x63\x82\x53\x63":
        return None
    bootp = bytearray(236)
    bootp[0] = 2
    bootp[1:4] = request[1:4]
    bootp[4:12] = request[4:12]
    bootp[16:20] = socket.inet_aton(CLIENT_ADDRESS)
    bootp[20:24] = socket.inet_aton(SERVICE_ADDRESS)
    bootp[24:28] = request[24:28]
    bootp[28:44] = request[28:44]
    server = socket.inet_aton(SERVICE_ADDRESS)
    options = bytearray(b"\x63\x82\x53\x63")
    options += dhcp_option(53, bytes((message_type,)))
    options += dhcp_option(54, server)
    options += dhcp_option(51, struct.pack("!I", 3600))
    options += dhcp_option(1, socket.inet_aton(SUBNET_MASK))
    options += dhcp_option(3, server)
    options += dhcp_option(6, server)
    options += dhcp_option(15, b"jio.com")
    options += dhcp_option(42, server)
    options += b"\xff"
    return bytes(bootp) + bytes(options)

def dhcp_loop(sock):
    while _running.is_set():
        try:
            request, peer = sock.recvfrom(2048)
            options = parse_dhcp_options(request)
            requested_type = options.get(53, b"\x01")
            if len(requested_type) != 1 or requested_type[0] not in (1, 3):
                continue
            reply_type = 2 if requested_type[0] == 1 else 5
            reply = make_dhcp_reply(request, reply_type)
            if reply:
                try:
                    sock.sendto(reply, ("255.255.255.255", 68))
                except Exception:
                    pass
                try:
                    sock.sendto(reply, (SERVICE_BROADCAST_ADDRESS, 68))
                except Exception:
                    pass
                print(f"[DHCP] reply type {reply_type} sent for client {peer[0]}", flush=True)
        except Exception:
            continue

def ntp_loop(sock):
    while _running.is_set():
        try:
            data, addr = sock.recvfrom(1024)
            if len(data) >= 48:
                packet = bytearray(48)
                packet[0] = 0x24
                packet[1] = 2
                packet[2] = 6
                packet[3] = 0xEC
                packet[4:8] = b'\x00\x00\x00\x01'
                packet[8:12] = b'\x00\x00\x00\x01'
                packet[12:16] = b'LOCL'
                # Enforce active certificate window (September 1, 2026 = 1788220800)
                # Guarantees both eMudhra (May 2025 - Dec 2028) and RILROOTCA chains are active!
                target_epoch = max(int(time.time()), 1788220800)
                now_sec = target_epoch + 2208988800
                ntp_ts = (now_sec << 32).to_bytes(8, 'big')
                packet[16:24] = ntp_ts
                packet[24:32] = data[40:48]
                packet[32:40] = ntp_ts
                packet[40:48] = ntp_ts
                sock.sendto(packet, addr)
                print(f"[NTP] Request answered for {addr[0]} (synced to active cert epoch 2026)", flush=True)
        except socket.timeout:
            continue
        except Exception:
            pass

def handle_http_portal(conn, addr):
    try:
        data = conn.recv(1024)
        if data:
            req_line = data.decode('latin1', errors='ignore').split('\r\n')[0]
            if "network/check" in req_line:
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
                print(msg, flush=True)
                try:
                    with open(BASE / "captive_wifi_lab.log", "a", encoding="utf-8") as lf:
                        lf.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
                except Exception:
                    pass
                return
            
            msg = f"[PORTAL] {addr[0]} >>> {req_line} -> returning HTTP 204"
            print(msg, flush=True)
            try:
                with open(BASE / "captive_wifi_lab.log", "a", encoding="utf-8") as lf:
                    lf.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            except Exception:
                pass
        resp = b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        conn.sendall(resp)
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

def http_portal_loop():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(('0.0.0.0', 80))
        s.listen(10)
        s.settimeout(1.0)
        print("[PORTAL] HTTP 204 responder listening on port 80", flush=True)
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
        try:
            s.close()
        except Exception:
            pass

def dot_blocker():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(('0.0.0.0', 853))
        s.listen(5)
        s.settimeout(1.0)
        print("[DoT] Port 853 blocker listening (forcing cleartext DNS)", flush=True)
        while _running.is_set():
            try:
                conn, addr = s.accept()
                conn.close()
                print(f"[DoT] Blocked DoT request from {addr[0]}", flush=True)
            except socket.timeout:
                continue
            except Exception:
                break
    except Exception as e:
        print(f"[DoT-ERR] Port 853 error: {e}", flush=True)
    finally:
        try:
            s.close()
        except Exception:
            pass

def main():
    print(f"===========================================================", flush=True)
    print(f"  WI-FI HOTSPOT CAPTIVE LAB (Subnet: 192.168.137.0/24)      ", flush=True)
    print(f"  Gateway & DNS: {SERVICE_ADDRESS}", flush=True)
    print(f"  Fake ACS IP:   {FAKE_ACS_IP} (acs.oss.jio.com)", flush=True)
    print(f"===========================================================", flush=True)

    try:
        with open(BASE / "captive_wifi_lab.log", "a", encoding="utf-8") as lf:
            lf.write(f"[{time.strftime('%H:%M:%S')}] [INIT] Wi-Fi Hotspot Captive Lab started on {SERVICE_ADDRESS}\n")
    except Exception:
        pass

    threads = []
    
    # 1. DNS UDP
    udp_dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        udp_dns.bind(('0.0.0.0', DNS_PORT))
    except (PermissionError, OSError) as e:
        print(f"[!] Warning: Cannot bind 0.0.0.0:{DNS_PORT} ({e}). Retrying on {SERVICE_ADDRESS}:{DNS_PORT}...", flush=True)
        try:
            udp_dns.bind((SERVICE_ADDRESS, DNS_PORT))
            print(f"[+] Fallback successful: Bound UDP DNS directly to {SERVICE_ADDRESS}:{DNS_PORT}", flush=True)
        except (PermissionError, OSError) as e2:
            print(f"\n==========================================================", flush=True)
            print(f"[ERROR] Port {DNS_PORT} (DNS) is blocked or in use by another process!", flush=True)
            print(f"==========================================================", flush=True)
            print(f"Common causes and fixes on Windows:", flush=True)
            print(f" 1. Quick Heal / 3rd-Party Antivirus Firewall is blocking Port 53:", flush=True)
            print(f"    -> Right-click green Quick Heal icon in taskbar tray -> 'Pause Protection' (15 mins)", flush=True)
            print(f" 2. Windows Mobile Hotspot DNS proxy (SharedAccess) is holding Port 53:", flush=True)
            print(f"    -> Open Admin PowerShell and run: Stop-Service SharedAccess -Force", flush=True)
            print(f" 3. An orphaned python.exe process is still running:", flush=True)
            print(f"    -> Run: taskkill /F /IM python.exe", flush=True)
            print(f" 4. Another DNS service is running (WSL2, Docker Desktop, AdGuard, etc.).", flush=True)
            print(f"==========================================================\n", flush=True)
            sys.exit(1)
    threads.append(threading.Thread(target=udp_dns_loop, args=(udp_dns,), daemon=True))

    # 2. DNS TCP
    dns_tcp = None
    try:
        dns_tcp = ThreadedDnsTcpServer(('0.0.0.0', DNS_PORT), DnsTcpHandler)
    except (PermissionError, OSError) as e:
        print(f"[!] Warning: Cannot bind TCP 0.0.0.0:{DNS_PORT}. Retrying on {SERVICE_ADDRESS}:{DNS_PORT}...", flush=True)
        try:
            dns_tcp = ThreadedDnsTcpServer((SERVICE_ADDRESS, DNS_PORT), DnsTcpHandler)
        except (PermissionError, OSError):
            print(f"[!] Warning: TCP DNS on port {DNS_PORT} unavailable. Using UDP DNS only.", flush=True)
    if dns_tcp:
        threads.append(threading.Thread(target=dns_tcp.serve_forever, daemon=True))

    # 3. NTP UDP
    ntp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ntp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ntp.bind(('0.0.0.0', 123))
    ntp.settimeout(1.0)
    threads.append(threading.Thread(target=ntp_loop, args=(ntp,), daemon=True))

    # 4. DHCP Server (Gracefully handles Windows Mobile Hotspot ICS coexistence)
    dhcp = None
    try:
        dhcp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dhcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        dhcp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        dhcp.bind(('0.0.0.0', DHCP_PORT))
        threads.append(threading.Thread(target=dhcp_loop, args=(dhcp,), daemon=True))
        print("[DHCP] Standalone DHCP server listening on UDP 67", flush=True)
    except OSError:
        print("[DHCP] Port 67 in use by Windows Mobile Hotspot ICS (SharedAccess). Using Windows DHCP.", flush=True)

    # 5. DoT Blocker (Port 853)
    threads.append(threading.Thread(target=dot_blocker, daemon=True))

    # 6. HTTP 204 Portal (Port 80)
    threads.append(threading.Thread(target=http_portal_loop, daemon=True))

    PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    for t in threads:
        t.start()

    print("\n[READY] Wi-Fi Captive Lab is active. Waiting for Jio STB to connect...", flush=True)
    print(">>> NOW POWER-CYCLE (REBOOT) THE JIO STB: Unplug power from back, wait 5s, plug back in! <<<", flush=True)
    print(">>> NOTE: If STB loops on /generate_204 or fails TLS, Factory Reset the STB to clear backoff! <<<", flush=True)
    try:
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _running.clear()
        try:
            udp_dns.close()
        except Exception:
            pass
        if dhcp:
            try:
                dhcp.close()
            except Exception:
                pass
        try:
            ntp.close()
        except Exception:
            pass
        try:
            dns_tcp.shutdown()
            dns_tcp.server_close()
        except Exception:
            pass
        try:
            PID_FILE.unlink()
        except Exception:
            pass
        print("[STOPPED] Wi-Fi Captive Lab shut down.", flush=True)

if __name__ == "__main__":
    main()
