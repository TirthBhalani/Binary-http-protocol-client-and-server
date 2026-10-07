#!/usr/bin/env python3
"""
bcurl — Binary HTTP client (BHTTP/1.0)

Usage:
    python bcurl.py [-v] host:port/path

Examples:
    python bcurl.py localhost:9000/index.html
    python bcurl.py -v localhost:9000/hello.txt

-v   write an annotated hex dump of every frame to stderr before/after
     sending or receiving, then print the response headers to stderr.

Exit codes:
    0   2xx response
    1   4xx or 5xx response, or connection / protocol error

The client opens exactly one TCP connection and never opens another.
"""

import socket
import sys

from protocol import (
    FLAG_END_HEADERS,
    FLAG_END_STREAM,
    FRAME_RESPONSE,
    build_request,
    encode_frame,
    parse_response,
    recv_frame,
)


# ---------------------------------------------------------------------------
# Hex dump
# ---------------------------------------------------------------------------

def _hexdump(data, label):
    print(f"\n--- {label} ({len(data)} bytes) ---", file=sys.stderr)
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        asc_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"  {i:04x}  {hex_part:<48}  |{asc_part}|", file=sys.stderr)
    print(file=sys.stderr)


def _annotate_request(frame, method, path):
    """Print a field-by-field breakdown of a REQUEST frame to stderr."""
    print("  [frame header]", file=sys.stderr)
    length = int.from_bytes(frame[0:3], "big")
    print(f"    00-02  {frame[0]:02x} {frame[1]:02x} {frame[2]:02x}"
          f"             length = {length}", file=sys.stderr)
    print(f"    03     {frame[3]:02x}                   type   = 0x00 (REQUEST)", file=sys.stderr)
    print(f"    04     {frame[4]:02x}                   flags  = 0x{frame[4]:02x}"
          f"  (END_HEADERS | END_STREAM)", file=sys.stderr)
    sid = int.from_bytes(frame[5:9], "big") & 0x7FFFFFFF
    print(f"    05-08  {frame[5]:02x} {frame[6]:02x} {frame[7]:02x} {frame[8]:02x}"
          f"          stream id = {sid}", file=sys.stderr)
    print("  [payload]", file=sys.stderr)
    off = 9
    ml = frame[off]
    m_bytes = frame[off + 1: off + 1 + ml]
    print(f"    {off:04x}  {ml:02x}                   method length = {ml}", file=sys.stderr)
    off += 1
    print(f"    {off:04x}  {' '.join(f'{b:02x}' for b in m_bytes):<23}"
          f"  method = {method!r}", file=sys.stderr)
    off += ml
    pl = int.from_bytes(frame[off:off + 2], "big")
    p_bytes = frame[off + 2: off + 2 + pl]
    print(f"    {off:04x}  {frame[off]:02x} {frame[off+1]:02x}"
          f"                 path length = {pl}", file=sys.stderr)
    off += 2
    print(f"    {off:04x}  {' '.join(f'{b:02x}' for b in p_bytes):<23}"
          f"  path = {path!r}", file=sys.stderr)
    off += pl
    hc = int.from_bytes(frame[off:off + 2], "big")
    print(f"    {off:04x}  {frame[off]:02x} {frame[off+1]:02x}"
          f"                 header count = {hc}", file=sys.stderr)
    print(file=sys.stderr)


def _annotate_response(frame, status):
    """Print a field-by-field breakdown of a RESPONSE frame to stderr."""
    print("  [frame header]", file=sys.stderr)
    length = int.from_bytes(frame[0:3], "big")
    print(f"    00-02  {frame[0]:02x} {frame[1]:02x} {frame[2]:02x}"
          f"             length = {length}", file=sys.stderr)
    print(f"    03     {frame[3]:02x}                   type   = 0x01 (RESPONSE)", file=sys.stderr)
    print(f"    04     {frame[4]:02x}                   flags  = 0x{frame[4]:02x}", file=sys.stderr)
    sid = int.from_bytes(frame[5:9], "big") & 0x7FFFFFFF
    print(f"    05-08  {frame[5]:02x} {frame[6]:02x} {frame[7]:02x} {frame[8]:02x}"
          f"          stream id = {sid}", file=sys.stderr)
    print("  [payload]", file=sys.stderr)
    print(f"    0009  {frame[9]:02x} {frame[10]:02x}"
          f"                 status code = {status}", file=sys.stderr)
    hc = int.from_bytes(frame[11:13], "big")
    print(f"    000b  {frame[11]:02x} {frame[12]:02x}"
          f"                 header count = {hc}", file=sys.stderr)
    print(file=sys.stderr)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_target(target):
    """Parse 'host:port/path' into (host, port, path).
    Defaults to port 9000 and path '/' if omitted."""
    if "/" not in target:
        target += "/"
    host_port, _, tail = target.partition("/")
    path = "/" + tail

    if ":" in host_port:
        host, port_str = host_port.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            sys.exit(f"error: invalid port: {port_str!r}")
    else:
        host = host_port
        port = 9000

    return host, port, path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    verbose = False
    args = sys.argv[1:]

    if "-v" in args:
        verbose = True
        args.remove("-v")

    if not args:
        sys.exit("usage: python bcurl.py [-v] host:port/path")

    host, port, path = _parse_target(args[0])

    req_headers = [
        ("host",       f"{host}:{port}"),
        ("user-agent", "bcurl/1.0"),
        ("accept",     "*/*"),
    ]

    frame_bytes = build_request("GET", path, req_headers)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((host, port))
    except OSError as exc:
        sys.exit(f"error: cannot connect to {host}:{port} — {exc}")

    if verbose:
        _hexdump(frame_bytes, f"REQUEST FRAME  GET {path}")
        _annotate_request(frame_bytes, "GET", path)

    sock.sendall(frame_bytes)

    try:
        frame_type, flags, stream_id, payload = recv_frame(sock)
    except ConnectionError as exc:
        sys.exit(f"error: {exc}")
    finally:
        sock.close()   # single connection — close as soon as the response is read

    if frame_type != FRAME_RESPONSE:
        sys.exit(f"error: expected RESPONSE frame (0x01), got type 0x{frame_type:02x}")

    status, resp_headers, body = parse_response(payload)

    if verbose:
        # Reconstruct the raw frame bytes for the hexdump.
        raw = encode_frame(FRAME_RESPONSE, FLAG_END_HEADERS | FLAG_END_STREAM, stream_id, payload)
        _hexdump(raw, f"RESPONSE FRAME  {status}")
        _annotate_response(raw, status)
        print("--- RESPONSE HEADERS ---", file=sys.stderr)
        for name, value in resp_headers:
            print(f"  {name}: {value}", file=sys.stderr)
        print(file=sys.stderr)

    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()

    if status >= 400:
        sys.exit(1)


if __name__ == "__main__":
    main()
