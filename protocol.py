"""
BHTTP/1.0 — Binary HTTP Protocol
Shared frame encoder / decoder used by both bserve and bcurl.

Frame header layout (9 bytes, big-endian):
  [Length 24][Type 8][Flags 8][R 1][Stream ID 31]
"""

import struct
import socket

FRAME_HEADER_SIZE = 9

# Frame types
FRAME_REQUEST  = 0x00
FRAME_RESPONSE = 0x01
FRAME_DATA     = 0x02   # reserved, skip cleanly
FRAME_GOAWAY   = 0x03   # reserved, skip cleanly

# Flags (OR-combined into the Flags byte)
FLAG_END_STREAM  = 0x01
FLAG_END_HEADERS = 0x04

# Static header name table — the ten most common names get an integer index.
# A sender uses the index instead of the full string; a receiver maps it back.
# Any name not in this table is sent as a length-prefixed literal (index 0x00).
STATIC_TABLE = {
    "host":            1,
    "content-type":    2,
    "content-length":  3,
    "user-agent":      4,
    "accept":          5,
    "accept-encoding": 6,
    "connection":      7,
    "server":          8,
    "date":            9,
    "last-modified":   10,
}
STATIC_TABLE_REVERSE = {v: k for k, v in STATIC_TABLE.items()}

_KNOWN_TYPES = {FRAME_REQUEST, FRAME_RESPONSE, FRAME_DATA, FRAME_GOAWAY}


# ---------------------------------------------------------------------------
# Internal string helpers
# ---------------------------------------------------------------------------

def _encode_lenpfx(s):
    """2-byte big-endian length prefix followed by the UTF-8 bytes of s."""
    if isinstance(s, str):
        s = s.encode("utf-8")
    return struct.pack("!H", len(s)) + s


def _decode_lenpfx(data, offset):
    """Read a 2-byte length-prefixed string from data at offset.
    Returns (string, new_offset)."""
    (length,) = struct.unpack_from("!H", data, offset)
    offset += 2
    value = data[offset:offset + length].decode("utf-8")
    return value, offset + length


# ---------------------------------------------------------------------------
# Header encoding
# ---------------------------------------------------------------------------

def encode_headers(headers):
    """
    Encode a list of (name, value) pairs.

    Wire format per entry:
      Indexed name  : [0x80|idx (1)] [value_len (2)] [value]
      Literal name  : [0x00 (1)] [name_len (2)] [name] [value_len (2)] [value]

    The count of entries is written first as a 2-byte big-endian integer.
    """
    out = struct.pack("!H", len(headers))
    for name, value in headers:
        key = name.lower()
        if key in STATIC_TABLE:
            out += struct.pack("B", 0x80 | STATIC_TABLE[key])
        else:
            out += b"\x00" + _encode_lenpfx(key)
        out += _encode_lenpfx(value)
    return out


def decode_headers(data, offset):
    """Decode headers encoded with encode_headers.
    Returns ([(name, value), ...], new_offset)."""
    (count,) = struct.unpack_from("!H", data, offset)
    offset += 2
    headers = []
    for _ in range(count):
        flag = data[offset]
        offset += 1
        if flag & 0x80:
            idx = flag & 0x7F
            name = STATIC_TABLE_REVERSE.get(idx, f"x-unknown-{idx}")
        else:
            name, offset = _decode_lenpfx(data, offset)
        value, offset = _decode_lenpfx(data, offset)
        headers.append((name, value))
    return headers, offset


# ---------------------------------------------------------------------------
# Frame encoding / decoding
# ---------------------------------------------------------------------------

def encode_frame(frame_type, flags, stream_id, payload):
    """Pack a 9-byte frame header followed by payload bytes."""
    length_bytes = struct.pack("!I", len(payload))[1:]   # drop the high byte → 3 bytes
    header = length_bytes + struct.pack("BB", frame_type, flags)
    header += struct.pack("!I", stream_id & 0x7FFFFFFF)  # clear reserved bit
    return header + payload


def decode_frame_header(raw9):
    """Parse exactly 9 bytes into (payload_length, frame_type, flags, stream_id).
    Raises ValueError if the buffer is too short."""
    if len(raw9) < FRAME_HEADER_SIZE:
        raise ValueError(f"frame header too short: got {len(raw9)} bytes, need {FRAME_HEADER_SIZE}")
    (length,) = struct.unpack("!I", b"\x00" + raw9[0:3])
    frame_type = raw9[3]
    flags      = raw9[4]
    (stream_id,) = struct.unpack("!I", raw9[5:9])
    stream_id &= 0x7FFFFFFF
    return length, frame_type, flags, stream_id


# ---------------------------------------------------------------------------
# Socket helpers
# ---------------------------------------------------------------------------

def recv_exact(sock, n):
    """Read exactly n bytes from sock.  Raises ConnectionError on EOF."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed before all bytes were received")
        buf += chunk
    return buf


def recv_frame(sock):
    """
    Read one complete frame from sock.

    If the frame type is not in the known set, the payload is consumed and
    discarded so the connection remains usable for the next frame.
    This is the mandatory forward-compatibility rule: a receiver MUST skip
    frames whose type it does not recognise, using the Length field to know
    how many bytes to discard.

    Returns (frame_type, flags, stream_id, payload).
    """
    while True:
        raw_header = recv_exact(sock, FRAME_HEADER_SIZE)
        length, frame_type, flags, stream_id = decode_frame_header(raw_header)
        payload = recv_exact(sock, length)
        if frame_type in _KNOWN_TYPES:
            return frame_type, flags, stream_id, payload
        # Unknown type: payload already consumed — loop and read the next frame.


# ---------------------------------------------------------------------------
# REQUEST frame helpers
# ---------------------------------------------------------------------------

def build_request(method, path, headers, body=b"", stream_id=1):
    """
    Build a REQUEST frame.

    Payload layout:
      [method_len (1)] [method] [path_len (2)] [path] [headers] [body]
    """
    m = method.encode("utf-8")
    payload  = struct.pack("B", len(m)) + m
    payload += _encode_lenpfx(path)
    payload += encode_headers(headers)
    payload += body
    flags = FLAG_END_HEADERS | FLAG_END_STREAM
    return encode_frame(FRAME_REQUEST, flags, stream_id, payload)


def parse_request(payload):
    """Parse a REQUEST frame payload.
    Returns (method, path, headers, body)."""
    offset = 0
    method_len = payload[offset]
    offset += 1
    method = payload[offset:offset + method_len].decode("utf-8")
    offset += method_len
    path, offset = _decode_lenpfx(payload, offset)
    headers, offset = decode_headers(payload, offset)
    body = payload[offset:]
    return method, path, headers, body


# ---------------------------------------------------------------------------
# RESPONSE frame helpers
# ---------------------------------------------------------------------------

def build_response(status_code, headers, body=b"", stream_id=1):
    """
    Build a RESPONSE frame.

    Payload layout:
      [status_code (2)] [headers] [body]
    """
    payload  = struct.pack("!H", status_code)
    payload += encode_headers(headers)
    payload += body
    flags = FLAG_END_HEADERS | FLAG_END_STREAM
    return encode_frame(FRAME_RESPONSE, flags, stream_id, payload)


def parse_response(payload):
    """Parse a RESPONSE frame payload.
    Returns (status_code, headers, body)."""
    offset = 0
    (status_code,) = struct.unpack_from("!H", payload, offset)
    offset += 2
    headers, offset = decode_headers(payload, offset)
    body = payload[offset:]
    return status_code, headers, body
