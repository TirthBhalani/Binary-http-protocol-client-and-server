"""
Integration tests for bserve.

Starts a real bserve instance in a background thread, then connects to it
directly using the protocol module. Tests cover the full request/response
lifecycle over an actual TCP socket.
"""

import importlib.util
import os
import socket
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protocol import (
    FRAME_REQUEST,
    FRAME_RESPONSE,
    build_request,
    encode_frame,
    parse_response,
    recv_frame,
)

# Load bserve as a module without running main().
_BSERVE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bserve.py"
)
_spec = importlib.util.spec_from_file_location("bserve", _BSERVE_PATH)
bserve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bserve)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

_PORT_BASE = 19900  # high ports to avoid conflicts


def _make_server_socket(port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(8)
    srv.settimeout(3)
    return srv


def _start_server(tmpdir, port):
    srv = _make_server_socket(port)

    def loop():
        try:
            while True:
                try:
                    conn, addr = srv.accept()
                except socket.timeout:
                    break
                t = threading.Thread(
                    target=bserve.handle_client,
                    args=(conn, addr, tmpdir),
                    daemon=True,
                )
                t.start()
        except Exception:
            pass

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    time.sleep(0.1)  # give the thread time to call accept()
    return srv


def _get(host, port, path, headers=None):
    """Send one GET request and return (status, headers, body)."""
    if headers is None:
        headers = [("host", f"{host}:{port}"), ("user-agent", "test/1.0")]
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    sock.sendall(build_request("GET", path, headers))
    frame_type, _, _, payload = recv_frame(sock)
    sock.close()
    assert frame_type == FRAME_RESPONSE, f"expected RESPONSE, got {frame_type}"
    return parse_response(payload)


# ---------------------------------------------------------------------------
# Normal responses
# ---------------------------------------------------------------------------

class TestNormalResponses(unittest.TestCase):
    port = _PORT_BASE

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        with open(os.path.join(cls.tmpdir, "hello.txt"), "wb") as f:
            f.write(b"hello world\n")
        with open(os.path.join(cls.tmpdir, "index.html"), "wb") as f:
            f.write(b"<h1>Hello, bserve!</h1>\n")
        with open(os.path.join(cls.tmpdir, "data.json"), "wb") as f:
            f.write(b'{"ok": true}\n')
        cls.srv = _start_server(cls.tmpdir, cls.port)

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def test_200_text_file(self):
        status, _, body = _get("127.0.0.1", self.port, "/hello.txt")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"hello world\n")

    def test_200_html_file(self):
        status, _, body = _get("127.0.0.1", self.port, "/index.html")
        self.assertEqual(status, 200)
        self.assertIn(b"Hello, bserve!", body)

    def test_200_json_file(self):
        status, _, body = _get("127.0.0.1", self.port, "/data.json")
        self.assertEqual(status, 200)
        self.assertIn(b'"ok"', body)

    def test_404_missing_file(self):
        status, _, _ = _get("127.0.0.1", self.port, "/no-such-file.txt")
        self.assertEqual(status, 404)

    def test_content_type_html(self):
        status, headers, _ = _get("127.0.0.1", self.port, "/index.html")
        header_map = dict(headers)
        self.assertEqual(status, 200)
        self.assertIn("text/html", header_map.get("content-type", ""))

    def test_content_type_text(self):
        status, headers, _ = _get("127.0.0.1", self.port, "/hello.txt")
        header_map = dict(headers)
        self.assertIn("text/plain", header_map.get("content-type", ""))

    def test_content_length_matches_body(self):
        status, headers, body = _get("127.0.0.1", self.port, "/hello.txt")
        header_map = dict(headers)
        self.assertEqual(int(header_map["content-length"]), len(body))

    def test_server_header_present(self):
        _, headers, _ = _get("127.0.0.1", self.port, "/hello.txt")
        header_map = dict(headers)
        self.assertIn("server", header_map)

    def test_date_header_present(self):
        _, headers, _ = _get("127.0.0.1", self.port, "/hello.txt")
        header_map = dict(headers)
        self.assertIn("date", header_map)


# ---------------------------------------------------------------------------
# Persistent connection (multiple requests on one socket)
# ---------------------------------------------------------------------------

class TestPersistentConnection(unittest.TestCase):
    port = _PORT_BASE + 1

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        with open(os.path.join(cls.tmpdir, "a.txt"), "wb") as f:
            f.write(b"aaa\n")
        with open(os.path.join(cls.tmpdir, "b.txt"), "wb") as f:
            f.write(b"bbb\n")
        cls.srv = _start_server(cls.tmpdir, cls.port)

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def test_two_requests_one_connection(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", self.port))
        try:
            for path, expected_body in [("/a.txt", b"aaa\n"), ("/b.txt", b"bbb\n")]:
                sock.sendall(build_request("GET", path, [("host", "test")], stream_id=1))
                _, _, _, payload = recv_frame(sock)
                status, _, body = parse_response(payload)
                self.assertEqual(status, 200)
                self.assertEqual(body, expected_body)
        finally:
            sock.close()

    def test_five_sequential_requests(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", self.port))
        try:
            for i in range(5):
                path = "/a.txt" if i % 2 == 0 else "/b.txt"
                sock.sendall(build_request("GET", path, [("host", "test")]))
                _, _, _, payload = recv_frame(sock)
                status, _, _ = parse_response(payload)
                self.assertEqual(status, 200)
        finally:
            sock.close()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling(unittest.TestCase):
    port = _PORT_BASE + 2

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        with open(os.path.join(cls.tmpdir, "ok.txt"), "wb") as f:
            f.write(b"ok\n")
        cls.srv = _start_server(cls.tmpdir, cls.port)

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def test_path_traversal_rejected(self):
        status, _, _ = _get("127.0.0.1", self.port, "/../etc/passwd")
        self.assertEqual(status, 400)

    def test_malformed_payload_returns_400(self):
        # Valid frame header, garbage payload — parse_request should fail.
        bad_frame = encode_frame(FRAME_REQUEST, 0x05, 1, b"\xff\xff\xff\xff\xff")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", self.port))
        sock.sendall(bad_frame)
        _, _, _, payload = recv_frame(sock)
        sock.close()
        status, _, _ = parse_response(payload)
        self.assertEqual(status, 400)

    def test_404_body_non_empty(self):
        status, _, body = _get("127.0.0.1", self.port, "/missing.html")
        self.assertEqual(status, 404)
        self.assertTrue(len(body) > 0)

    def test_server_recovers_after_bad_request(self):
        # Send a bad frame, then a good one — server should answer both.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", self.port))
        bad = encode_frame(FRAME_REQUEST, 0x05, 1, b"\xff\xff")
        sock.sendall(bad)
        _, _, _, payload = recv_frame(sock)
        status_bad, _, _ = parse_response(payload)
        self.assertEqual(status_bad, 400)

        sock.sendall(build_request("GET", "/ok.txt", [("host", "test")]))
        _, _, _, payload = recv_frame(sock)
        status_ok, _, body = parse_response(payload)
        self.assertEqual(status_ok, 200)
        self.assertEqual(body, b"ok\n")
        sock.close()


# ---------------------------------------------------------------------------
# Unknown frame skipping (forward-compatibility rule)
# ---------------------------------------------------------------------------

class TestUnknownFrameSkipping(unittest.TestCase):
    port = _PORT_BASE + 3

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        with open(os.path.join(cls.tmpdir, "z.txt"), "wb") as f:
            f.write(b"zzz\n")
        cls.srv = _start_server(cls.tmpdir, cls.port)

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def test_unknown_frame_is_skipped(self):
        """
        Send an unknown frame type (0xEE) followed by a valid REQUEST.
        The server must skip the unknown frame and respond to the REQUEST.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", self.port))
        # Unknown frame type 0xEE with 4-byte payload.
        unknown = encode_frame(0xEE, 0x00, 0, b"\x01\x02\x03\x04")
        sock.sendall(unknown)
        # Now send a real request.
        sock.sendall(build_request("GET", "/z.txt", [("host", "test")]))
        _, _, _, payload = recv_frame(sock)
        sock.close()
        status, _, body = parse_response(payload)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"zzz\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
