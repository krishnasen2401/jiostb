from pathlib import Path
import os
import socket
import socketserver
import struct
import threading
import time

BASE = Path(__file__).resolve().parent
PID_FILE = BASE / "captive-lab.pid"
SERVICE_ADDRESS = "192.168.50.1"
SERVICE_BROADCAST_ADDRESS = "192.168.50.255"
FAKE_ACS_IP = "49.44.112.10" 
FAKE_GOOGLE_IP = "142.250.190.46" 
DNS_PORT = 53
DHCP_PORT = 67
CLIENT_ADDRESS = "192.168.50.2"
SUBNET_MASK = "255.255.255.0"
_running = threading.Event()
_running.set()

def decode_name(packet, offset):
    labels = []
    cursor = offset
    next_offset = None
    visited = set()
    while True:
        if cursor >= len(packet) or cursor in visited: raise ValueError("invalid")
        visited.add(cursor)
        size = packet[cursor]
        if size & 0xC0 == 0xC0:
            if cursor + 1 >= len(packet): raise ValueError("truncated")
            pointer = ((size & 0x3F) << 8) | packet[cursor + 1]
            if next_offset is None: next_offset = cursor + 2
            cursor = pointer
            continue
        if size & 0xC0: raise ValueError("invalid")
        cursor += 1
        if size == 0:
            return ".".join(labels).lower(), (next_offset if next_offset is not None else cursor)
        labels.append(packet[cursor:cursor + size].decode("ascii", errors="strict"))
        cursor += size

def parse_question(packet):
    if len(packet) < 12: raise ValueError("short")
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
        elif "google" in name:
            resolved = FAKE_GOOGLE_IP
        else:
            resolved = SERVICE_ADDRESS
        ip_bytes = socket.inet_aton(resolved)
        answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 30, len(ip_bytes)) + ip_bytes
        answer_count = 1
        msg = f"[DNS] {client_ip} queried: {name} -> resolved: {resolved}"
        print(msg, flush=True)
        try:
            with open(BASE / "captive_lab.log", "a", encoding="utf-8") as lf:
                lf.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        except: pass
    elif qtype == 28:
        msg = f"[DNS-AAAA] {client_ip} queried IPv6: {name} -> NODATA"
        print(msg, flush=True)
        try:
            with open(BASE / "captive_lab.log", "a", encoding="utf-8") as lf:
                lf.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        except: pass
        
    header = struct.pack("!HHHHHH", query_id, flags, 1, answer_count, 0, 0)
    return header + query[12:question_end] + answer

def recv_exact(sock, length):
    data = bytearray()
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk: raise ConnectionError("closed")
        data.extend(chunk)
    return bytes(data)

class DnsTcpHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            size = struct.unpack("!H", recv_exact(self.request, 2))[0]
            query = recv_exact(self.request, size)
            answer = local_dns_answer(query, self.client_address[0])
            self.request.sendall(struct.pack("!H", len(answer)) + answer)
        except: return

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
            except: pass
            continue

def parse_dhcp_options(packet):
    options = {}
    offset = 240
    while offset < len(packet):
        code = packet[offset]
        offset += 1
        if code == 255: break
        if code == 0: continue
        size = packet[offset]
        offset += 1
        options[code] = packet[offset:offset + size]
        offset += size
    return options

def dhcp_option(code, value):
    return bytes((code, len(value))) + value

def make_dhcp_reply(request, message_type):
    if len(request) < 240 or request[236:240] != b"\x63\x82\x53\x63": return None
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
    options += b"\xff"
    return bytes(bootp) + bytes(options)

def dhcp_loop(sock):
    while _running.is_set():
        try:
            request, peer = sock.recvfrom(2048)
            options = parse_dhcp_options(request)
            requested_type = options.get(53, b"\x01")
            if len(requested_type) != 1 or requested_type[0] not in (1, 3): continue
            reply_type = 2 if requested_type[0] == 1 else 5
            reply = make_dhcp_reply(request, reply_type)
            if reply:
                try: sock.sendto(reply, ("255.255.255.255", 68))
                except: pass
                try: sock.sendto(reply, (SERVICE_BROADCAST_ADDRESS, 68))
                except: pass
                print(f"DHCP reply type {reply_type} sent for client {peer[0]}", flush=True)
        except: continue

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
                now = int(time.time()) + 2208988800
                packet[16:24] = now.to_bytes(8, 'big')
                packet[24:32] = data[40:48]
                packet[32:40] = now.to_bytes(8, 'big')
                packet[40:48] = now.to_bytes(8, 'big')
                sock.sendto(packet, addr)
                print(f"NTP Request answered for {addr[0]}", flush=True)
        except socket.timeout: continue
        except: pass

def handle_http_portal(conn, addr):
    try:
        data = conn.recv(1024)
        if data:
            req_line = data.decode('latin1', errors='ignore').split('\r\n')[0]
            msg = f"[PORTAL] {addr[0]} >>> {req_line} -> returning HTTP 204"
            print(msg, flush=True)
            try:
                with open(BASE / "captive_lab.log", "a", encoding="utf-8") as lf:
                    lf.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            except: pass
        resp = b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        conn.sendall(resp)
    except: pass
    finally:
        try: conn.close()
        except: pass

def http_portal_loop():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(('0.0.0.0', 80))
        s.listen(10)
        s.settimeout(1.0)
        print("HTTP 204 Captive Portal responder listening on port 80", flush=True)
        while _running.is_set():
            try:
                conn, addr = s.accept()
                threading.Thread(target=handle_http_portal, args=(conn, addr), daemon=True).start()
            except socket.timeout: continue
            except: break
    except Exception as e:
        print(f"Port 80 error: {e}", flush=True)
    finally:
        try: s.close()
        except: pass

def dot_blocker():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(('0.0.0.0', 853))
        s.listen(5)
        s.settimeout(1.0)
        while _running.is_set():
            try:
                conn, addr = s.accept()
                conn.close()
                print(f"DoT Request blocked from {addr[0]}", flush=True)
            except socket.timeout: continue
            except: break
    except Exception as e:
        print(f"[!] Warning: DoT blocker port 853 unavailable: {e}", flush=True)
    finally:
        try: s.close()
        except: pass

def main():
    print(f"Network setup started on {SERVICE_ADDRESS}", flush=True)
    threads = []

    # 1. UDP DNS
    udp_dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        udp_dns.bind(('0.0.0.0', DNS_PORT))
    except (PermissionError, OSError) as e:
        print(f"[!] Warning: Cannot bind 0.0.0.0:{DNS_PORT} ({e}). Retrying on {SERVICE_ADDRESS}:{DNS_PORT}...", flush=True)
        try:
            udp_dns.bind((SERVICE_ADDRESS, DNS_PORT))
        except (PermissionError, OSError) as e2:
            print(f"[ERROR] Port {DNS_PORT} (DNS) in use. Stop SharedAccess or Antivirus: {e2}", flush=True)
            sys.exit(1)
    threads.append(threading.Thread(target=udp_dns_loop, args=(udp_dns,), daemon=True))

    # 2. DHCP Server
    dhcp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dhcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    dhcp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        dhcp.bind(('0.0.0.0', DHCP_PORT))
    except (PermissionError, OSError) as e:
        print(f"[!] Warning: Cannot bind 0.0.0.0:{DHCP_PORT} ({e}). Retrying on {SERVICE_ADDRESS}:{DHCP_PORT}...", flush=True)
        try:
            dhcp.bind((SERVICE_ADDRESS, DHCP_PORT))
        except (PermissionError, OSError):
            print(f"[!] Warning: DHCP binding on {SERVICE_ADDRESS}:{DHCP_PORT} failed.", flush=True)
    threads.append(threading.Thread(target=dhcp_loop, args=(dhcp,), daemon=True))

    # 3. NTP Server
    ntp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ntp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ntp_bound = False
    try:
        ntp.bind(('0.0.0.0', 123))
        ntp_bound = True
    except (PermissionError, OSError) as e:
        print(f"[!] Warning: Cannot bind 0.0.0.0:123 ({e}). Trying {SERVICE_ADDRESS}:123...", flush=True)
        try:
            ntp.bind((SERVICE_ADDRESS, 123))
            ntp_bound = True
        except (PermissionError, OSError):
            print(f"[!] Warning: NTP port 123 unavailable (W32Time in use). Continuing without local NTP responder...", flush=True)
            ntp = None
    if ntp and ntp_bound:
        ntp.settimeout(1.0)
        threads.append(threading.Thread(target=ntp_loop, args=(ntp,), daemon=True))

    # 4. TCP DNS
    dns_tcp = None
    try:
        dns_tcp = ThreadedDnsTcpServer(('0.0.0.0', DNS_PORT), DnsTcpHandler)
    except (PermissionError, OSError):
        try:
            dns_tcp = ThreadedDnsTcpServer((SERVICE_ADDRESS, DNS_PORT), DnsTcpHandler)
        except (PermissionError, OSError):
            print(f"[!] Warning: TCP DNS on port {DNS_PORT} unavailable. Using UDP DNS only.", flush=True)
    if dns_tcp:
        threads.append(threading.Thread(target=dns_tcp.serve_forever, daemon=True))

    # 5. DoT & HTTP Portal
    threads.append(threading.Thread(target=dot_blocker, daemon=True))
    threads.append(threading.Thread(target=http_portal_loop, daemon=True))

    PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    for t in threads: t.start()
    print("Server is ready. Waiting for STB...", flush=True)
    try:
        while any(t.is_alive() for t in threads): 
            for t in threads: t.join(timeout=0.5)
    except KeyboardInterrupt: pass
    finally:
        _running.clear()
        try: udp_dns.close()
        except: pass
        try: dhcp.close()
        except: pass
        if ntp:
            try: ntp.close()
            except: pass
        if dns_tcp:
            try:
                dns_tcp.shutdown()
                dns_tcp.server_close()
            except: pass
        try: PID_FILE.unlink()
        except: pass

if __name__ == "__main__":
    main()