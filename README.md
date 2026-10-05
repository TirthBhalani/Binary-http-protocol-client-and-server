# BHTTP/1.0

Networks Architecture — Course Project: HTTP, In Binary.

The assignment asked for either a server or a client. Both are implemented here, out of curiosity. They interoperate with any other implementation that follows `spec.md`.

---

## What is in this repo

| File / Dir | Description |
|---|---|
| `spec.md` | Protocol specification (~2 pages) |
| `hexdump.md` | Annotated hexdump of one complete request and response |
| `protocol.py` | Shared frame encoder/decoder (used by both programs) |
| `bserve.py` | Binary HTTP server |
| `bcurl.py` | Binary HTTP client |
| `www/` | Sample static files for testing |
| `tests/` | Unit tests and integration tests |

---

## Quick start

**Terminal 1 — start the server:**
```
python bserve.py ./www 9000
```

**Terminal 2 — fetch a file:**
```
python bcurl.py localhost:9000/index.html
python bcurl.py localhost:9000/hello.txt
python bcurl.py localhost:9000/sample.json
```

**Verbose mode** (hexdumps every frame to stderr, body to stdout):
```
python bcurl.py -v localhost:9000/index.html
```

**Non-existent file (exit code 1):**
```
python bcurl.py localhost:9000/does-not-exist.txt
echo $?   # 1
```

---

## Running tests

Run everything:
```
python tests/run_tests.py
```

Unit tests only (no network required):
```
python tests/run_tests.py unit
```

Integration tests only (starts a real server in-process):
```
python tests/run_tests.py integ
```

---

## Protocol summary

See `spec.md` for the full specification. The short version:

- Every message is a **frame**: 9-byte fixed header followed by a variable payload.
- The header carries a 24-bit payload length, an 8-bit type, an 8-bit flags byte, and a 31-bit stream ID — the same layout as HTTP/2.
- Two frame types are in use: `REQUEST (0x00)` and `RESPONSE (0x01)`.
- Header names are compressed using a 10-entry static table (HPACK's first two mechanisms).
- Unknown frame types are silently skipped using the length field. This is the v2 compatibility hook.
- The server keeps the TCP connection open after every response.

---

## Deliverables

1. `spec.md` — the specification
2. `bserve.py` + `bcurl.py` — the programs
3. `hexdump.md` — annotated hexdump

---

## Requirements

Python 3.7 or later. No third-party packages.
