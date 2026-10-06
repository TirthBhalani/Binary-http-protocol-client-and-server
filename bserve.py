#!/usr/bin/env python3
"""
bserve — Binary HTTP server (BHTTP/1.0)

Usage:
    python bserve.py <root> <port>
    python bserve.py ./www 9000

Accepts persistent TCP connections. Each connection may carry any number of
REQUEST frames, each answered with one RESPONSE frame. The connection stays
open until the client closes it or sends a GOAWAY frame.

Status codes sent by this server:
    200  file found and delivered
    400  malformed REQUEST payload or disallowed path
    404  file not found under root
"""

import datetime
import mimetypes
import os
import posixpath
import socket
import struct
import sys
import threading

from protocol import (
    FRAME_REQUEST,
    FRAME_GOAWAY,
    recv_frame,
    parse_request,
    build_response,
)


def _date_now():
    return datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")


def _safe_file_path(root, url_path):
    """
    Map a URL path to an absolute file path under root.

    Returns the resolved path, or None if the path is a traversal attempt
    or would escape the root directory.
    """
    # Reject any path component that is or starts with '..'
    # before normalization so that '/../etc/passwd' is caught immediately.
    raw_parts = url_path.replace('\\', '/').split('/')
    if any(p == '..' or p.startswith('../') for p in raw_parts):
        return None

    # posixpath.normpath collapses . and leftover // in URL-style paths.
    clean = posixpath.normpath("/" + url_path.lstrip("/"))
    relative = clean.lstrip("/")
    parts = [p for p in relative.split("/") if p]
    candidate = os.path.join(root, *parts) if parts else root
    candidate = os.path.realpath(candidate)
    real_root = os.path.realpath(root)
    # Second guard: symlinks or other tricks that slip past the first check.
    if not candidate.startswith(real_root + os.sep) and candidate != real_root:
        return None
    return candidate


def handle_client(conn, addr, root):
    """Serve one persistent client connection until it closes or errors."""
    print(f"[+] {addr[0]}:{addr[1]} connected")
    try:
        while True:
            try:
                frame_type, flags, stream_id, payload = recv_frame(conn)
            except (ConnectionError, ValueError, struct.error) as exc:
                print(f"[-] {addr[0]}:{addr[1]} disconnected ({exc})")
                break

            if frame_type == FRAME_GOAWAY:
                print(f"[-] {addr[0]}:{addr[1]} sent GOAWAY")
                break

            if frame_type != FRAME_REQUEST:
                # recv_frame already consumed the payload; nothing more to do.
                continue

            # Parse the request payload.
            try:
                method, path, req_headers, body = parse_request(payload)
            except Exception:
                resp = build_response(
                    400,
                    [("server", "bserve/1.0"), ("date", _date_now())],
                    b"Bad Request",
                    stream_id,
                )
                conn.sendall(resp)
                continue

            print(f"    {method} {path}  (stream {stream_id})")

            file_path = _safe_file_path(root, path)
            if file_path is None:
                resp = build_response(
                    400,
                    [("server", "bserve/1.0"), ("date", _date_now())],
                    b"Bad Request",
                    stream_id,
                )
                conn.sendall(resp)
                continue

            if not os.path.isfile(file_path):
                resp = build_response(
                    404,
                    [("server", "bserve/1.0"), ("date", _date_now())],
                    b"Not Found",
                    stream_id,
                )
                conn.sendall(resp)
                continue

            with open(file_path, "rb") as f:
                data = f.read()

            mime, _ = mimetypes.guess_type(file_path)
            if mime is None:
                mime = "application/octet-stream"

            resp_headers = [
                ("content-type",   mime),
                ("content-length", str(len(data))),
                ("server",         "bserve/1.0"),
                ("date",           _date_now()),
            ]
            resp = build_response(200, resp_headers, data, stream_id)
            conn.sendall(resp)

    finally:
        conn.close()


def main():
    if len(sys.argv) != 3:
        sys.exit(f"usage: python {sys.argv[0]} <root> <port>")

    root = sys.argv[1]

    try:
        port = int(sys.argv[2])
    except ValueError:
        sys.exit("error: port must be an integer")

    if not os.path.isdir(root):
        sys.exit(f"error: '{root}' is not a directory")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("", port))
    server.listen(32)
    print(f"bserve listening on :{port}  root={os.path.abspath(root)}")

    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(
                target=handle_client,
                args=(conn, addr, root),
                daemon=True,
            )
            t.start()
    except KeyboardInterrupt:
        print("\nbserve shutting down")
    finally:
        server.close()


if __name__ == "__main__":
    main()
