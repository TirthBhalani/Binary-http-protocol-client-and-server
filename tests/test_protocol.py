"""
Unit tests for the BHTTP/1.0 frame encoder and decoder (protocol.py).
No network I/O — everything is tested against in-memory byte buffers.
"""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protocol import (
    FRAME_HEADER_SIZE,
    FRAME_REQUEST,
    FRAME_RESPONSE,
    FLAG_END_HEADERS,
    FLAG_END_STREAM,
    STATIC_TABLE,
    STATIC_TABLE_REVERSE,
    _encode_lenpfx,
    _decode_lenpfx,
    encode_headers,
    decode_headers,
    encode_frame,
    decode_frame_header,
    build_request,
    parse_request,
    build_response,
    parse_response,
)


# ---------------------------------------------------------------------------
# Frame header
# ---------------------------------------------------------------------------

class TestFrameHeader(unittest.TestCase):

    def test_header_is_9_bytes(self):
        raw = encode_frame(FRAME_REQUEST, 0, 1, b"")
        self.assertEqual(len(raw), FRAME_HEADER_SIZE)

    def test_roundtrip_type_and_flags(self):
        raw = encode_frame(FRAME_RESPONSE, 0x05, 42, b"payload")
        length, ftype, flags, sid = decode_frame_header(raw[:FRAME_HEADER_SIZE])
        self.assertEqual(length, len(b"payload"))
        self.assertEqual(ftype, FRAME_RESPONSE)
        self.assertEqual(flags, 0x05)
        self.assertEqual(sid, 42)

    def test_stream_id_reserved_bit_is_cleared(self):
        # Highest possible stream ID with reserved bit set — should be masked.
        raw = encode_frame(FRAME_REQUEST, 0, 0xFFFFFFFF, b"")
        _, _, _, sid = decode_frame_header(raw[:FRAME_HEADER_SIZE])
        self.assertEqual(sid, 0x7FFFFFFF)

    def test_length_field_occupies_3_bytes(self):
        # Payload of 0x010203 bytes → length bytes must be 01 02 03.
        big = b"x" * 0x010203
        raw = encode_frame(FRAME_REQUEST, 0, 1, big)
        self.assertEqual(raw[0], 0x01)
        self.assertEqual(raw[1], 0x02)
        self.assertEqual(raw[2], 0x03)

    def test_payload_appended_after_header(self):
        payload = b"\xde\xad\xbe\xef"
        raw = encode_frame(FRAME_REQUEST, 0, 1, payload)
        self.assertEqual(raw[FRAME_HEADER_SIZE:], payload)

    def test_short_header_raises_value_error(self):
        with self.assertRaises(ValueError):
            decode_frame_header(b"\x00\x00\x05\x00")  # only 4 bytes


# ---------------------------------------------------------------------------
# Length-prefixed strings
# ---------------------------------------------------------------------------

class TestLenPfx(unittest.TestCase):

    def test_encode_str_roundtrip(self):
        enc = _encode_lenpfx("hello")
        val, off = _decode_lenpfx(enc, 0)
        self.assertEqual(val, "hello")
        self.assertEqual(off, len(enc))

    def test_encode_bytes_roundtrip(self):
        enc = _encode_lenpfx(b"raw bytes")
        val, off = _decode_lenpfx(enc, 0)
        self.assertEqual(val, "raw bytes")

    def test_empty_string(self):
        enc = _encode_lenpfx("")
        val, _ = _decode_lenpfx(enc, 0)
        self.assertEqual(val, "")

    def test_unicode(self):
        # Non-ASCII should encode to UTF-8 and decode correctly.
        enc = _encode_lenpfx("caf\u00e9")
        val, _ = _decode_lenpfx(enc, 0)
        self.assertEqual(val, "café")

    def test_decode_at_offset(self):
        # Prefix the encoded string with junk to test non-zero offset.
        junk = b"\xff\xff"
        enc = junk + _encode_lenpfx("world")
        val, off = _decode_lenpfx(enc, 2)
        self.assertEqual(val, "world")


# ---------------------------------------------------------------------------
# Header encoding
# ---------------------------------------------------------------------------

class TestHeaderEncoding(unittest.TestCase):

    def test_empty_header_list(self):
        enc = encode_headers([])
        decoded, offset = decode_headers(enc, 0)
        self.assertEqual(decoded, [])
        self.assertEqual(offset, len(enc))

    def test_indexed_name_uses_0x80_prefix(self):
        enc = encode_headers([("host", "example.com")])
        # Bytes 0-1 are the count (0x00 0x01).
        # Byte 2 should be 0x80 | 1 = 0x81.
        self.assertEqual(enc[2], 0x81)

    def test_literal_name_uses_0x00_prefix(self):
        enc = encode_headers([("x-custom", "value")])
        self.assertEqual(enc[2], 0x00)

    def test_indexed_name_roundtrip(self):
        headers = [("host", "localhost:9000"), ("content-type", "text/html")]
        enc = encode_headers(headers)
        decoded, _ = decode_headers(enc, 0)
        self.assertEqual(decoded, headers)

    def test_literal_name_roundtrip(self):
        headers = [("x-request-id", "abc-123")]
        enc = encode_headers(headers)
        decoded, _ = decode_headers(enc, 0)
        self.assertEqual(decoded, [("x-request-id", "abc-123")])

    def test_all_static_table_names_roundtrip(self):
        headers = [(name, f"value-{i}") for i, name in enumerate(STATIC_TABLE)]
        enc = encode_headers(headers)
        decoded, _ = decode_headers(enc, 0)
        self.assertEqual(decoded, headers)

    def test_mixed_indexed_and_literal(self):
        headers = [
            ("content-type", "application/json"),
            ("x-trace-id", "trace-xyz"),
            ("server", "bserve/1.0"),
        ]
        enc = encode_headers(headers)
        decoded, _ = decode_headers(enc, 0)
        self.assertEqual(decoded, headers)

    def test_name_is_lowercased(self):
        enc = encode_headers([("Host", "example.com")])
        decoded, _ = decode_headers(enc, 0)
        self.assertEqual(decoded[0][0], "host")

    def test_count_field_is_2_bytes(self):
        enc = encode_headers([])
        # First two bytes = header count = 0
        (count,) = struct.unpack("!H", enc[:2])
        self.assertEqual(count, 0)


# ---------------------------------------------------------------------------
# REQUEST frame
# ---------------------------------------------------------------------------

class TestRequestFrame(unittest.TestCase):

    def _parse(self, frame):
        payload = frame[FRAME_HEADER_SIZE:]
        return parse_request(payload)

    def test_simple_get(self):
        frame = build_request("GET", "/index.html", [("host", "localhost")])
        method, path, headers, body = self._parse(frame)
        self.assertEqual(method, "GET")
        self.assertEqual(path, "/index.html")
        self.assertEqual(body, b"")

    def test_post_with_body(self):
        frame = build_request("POST", "/submit", [], b"name=alice")
        _, _, _, body = self._parse(frame)
        self.assertEqual(body, b"name=alice")

    def test_method_names(self):
        for m in ("GET", "POST", "PUT", "DELETE", "HEAD"):
            frame = build_request(m, "/", [])
            method, _, _, _ = self._parse(frame)
            self.assertEqual(method, m)

    def test_deep_path(self):
        frame = build_request("GET", "/a/b/c/d.html", [])
        _, path, _, _ = self._parse(frame)
        self.assertEqual(path, "/a/b/c/d.html")

    def test_binary_body_preserved(self):
        body = bytes(range(256))
        frame = build_request("POST", "/", [], body)
        _, _, _, out = self._parse(frame)
        self.assertEqual(out, body)

    def test_frame_type_is_request(self):
        frame = build_request("GET", "/", [])
        _, ftype, _, _ = decode_frame_header(frame[:FRAME_HEADER_SIZE])
        self.assertEqual(ftype, FRAME_REQUEST)

    def test_flags_set(self):
        frame = build_request("GET", "/", [])
        _, _, flags, _ = decode_frame_header(frame[:FRAME_HEADER_SIZE])
        self.assertEqual(flags, FLAG_END_HEADERS | FLAG_END_STREAM)

    def test_stream_id(self):
        frame = build_request("GET", "/", [], stream_id=7)
        _, _, _, sid = decode_frame_header(frame[:FRAME_HEADER_SIZE])
        self.assertEqual(sid, 7)


# ---------------------------------------------------------------------------
# RESPONSE frame
# ---------------------------------------------------------------------------

class TestResponseFrame(unittest.TestCase):

    def _parse(self, frame):
        payload = frame[FRAME_HEADER_SIZE:]
        return parse_response(payload)

    def test_200_with_body(self):
        frame = build_response(200, [("content-type", "text/plain")], b"hello")
        status, headers, body = self._parse(frame)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"hello")
        self.assertEqual(headers, [("content-type", "text/plain")])

    def test_status_codes(self):
        for code in (200, 201, 400, 404, 500):
            frame = build_response(code, [], b"")
            status, _, _ = self._parse(frame)
            self.assertEqual(status, code)

    def test_empty_body(self):
        frame = build_response(404, [], b"")
        _, _, body = self._parse(frame)
        self.assertEqual(body, b"")

    def test_binary_body(self):
        body = bytes(range(256))
        frame = build_response(200, [], body)
        _, _, out = self._parse(frame)
        self.assertEqual(out, body)

    def test_frame_type_is_response(self):
        frame = build_response(200, [], b"")
        _, ftype, _, _ = decode_frame_header(frame[:FRAME_HEADER_SIZE])
        self.assertEqual(ftype, FRAME_RESPONSE)

    def test_stream_id_roundtrip(self):
        frame = build_response(200, [], b"", stream_id=99)
        _, _, _, sid = decode_frame_header(frame[:FRAME_HEADER_SIZE])
        self.assertEqual(sid, 99)


# ---------------------------------------------------------------------------
# Static table completeness
# ---------------------------------------------------------------------------

class TestStaticTable(unittest.TestCase):

    def test_exactly_10_entries(self):
        self.assertEqual(len(STATIC_TABLE), 10)

    def test_indices_1_to_10(self):
        self.assertEqual(sorted(STATIC_TABLE.values()), list(range(1, 11)))

    def test_reverse_table_consistent(self):
        for name, idx in STATIC_TABLE.items():
            self.assertEqual(STATIC_TABLE_REVERSE[idx], name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
