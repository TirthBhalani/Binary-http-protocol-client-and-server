# Annotated Hexdump — BHTTP/1.0 Request and Response

This dump traces a single `GET /index.html` exchange between `bcurl` and `bserve`.
The server root contains `www/index.html` with the content `<h1>Hello, bserve!</h1>` (24 bytes).
Every byte on the wire is accounted for.

---

## Request Frame — `GET /index.html`  (63 bytes total)

Headers sent: `host: localhost:9000`, `user-agent: bcurl/1.0`, `accept: */*`

```
Offset   Hex                                                 Field
───────  ──────────────────────────────────────────────────  ──────────────────────────────────────────────
                    ┌─ frame header (9 bytes) ──────────────────────────────────────────────────────────┐
0x00     00 00 36                                            Length = 54  (payload bytes that follow)
0x03     00                                                  Type   = 0x00  (REQUEST)
0x04     05                                                  Flags  = 0x05  (END_HEADERS=0x04 | END_STREAM=0x01)
0x05     00 00 00 01                                         Stream ID = 1
                    └───────────────────────────────────────────────────────────────────────────────────┘
                    ┌─ payload (54 bytes) ──────────────────────────────────────────────────────────────┐
0x09     03                                                  Method length = 3
0x0a     47 45 54                                            Method = "GET"
0x0d     00 0b                                               Path length = 11
0x0f     2f 69 6e 64 65 78 2e 68 74 6d 6c                   Path = "/index.html"
0x1a     00 03                                               Header count = 3
                    ── header 1 ──────────────────────────────────────────────────────────────────────
0x1c     81                                                  Name = "host"  (indexed, table[1], 0x80|1)
0x1d     00 0e                                               Value length = 14
0x1f     6c 6f 63 61 6c 68 6f 73 74 3a 39 30 30 30          Value = "localhost:9000"
                    ── header 2 ──────────────────────────────────────────────────────────────────────
0x2d     84                                                  Name = "user-agent"  (indexed, table[4], 0x80|4)
0x2e     00 09                                               Value length = 9
0x30     62 63 75 72 6c 2f 31 2e 30                          Value = "bcurl/1.0"
                    ── header 3 ──────────────────────────────────────────────────────────────────────
0x39     85                                                  Name = "accept"  (indexed, table[5], 0x80|5)
0x3a     00 03                                               Value length = 3
0x3c     2a 2f 2a                                            Value = "*/*"
                    └───────────────────────────────────────────────────────────────────────────────────┘
```

**Raw bytes (63 bytes):**
```
0000  00 00 36 00 05 00 00 00  01 03 47 45 54 00 0b 2f  ..6.......GET../
0010  69 6e 64 65 78 2e 68 74  6d 6c 00 03 81 00 0e 6c  index.html....l
0020  6f 63 61 6c 68 6f 73 74  3a 39 30 30 30 84 00 09  ocalhost:9000...
0030  62 63 75 72 6c 2f 31 2e  30 85 00 03 2a 2f 2a     bcurl/1.0...*/*
```

---

## Response Frame — `200 OK`  (99 bytes total)

Response headers: `content-type`, `content-length`, `server`, `date`  
Body: 24-byte file content

```
Offset   Hex                                                 Field
───────  ──────────────────────────────────────────────────  ──────────────────────────────────────────────
                    ┌─ frame header (9 bytes) ──────────────────────────────────────────────────────────┐
0x00     00 00 5a                                            Length = 90  (payload bytes that follow)
0x03     01                                                  Type   = 0x01  (RESPONSE)
0x04     05                                                  Flags  = 0x05  (END_HEADERS=0x04 | END_STREAM=0x01)
0x05     00 00 00 01                                         Stream ID = 1  (echoed from request)
                    └───────────────────────────────────────────────────────────────────────────────────┘
                    ┌─ payload (90 bytes) ──────────────────────────────────────────────────────────────┐
0x09     00 c8                                               Status code = 200
0x0b     00 04                                               Header count = 4
                    ── header 1 ──────────────────────────────────────────────────────────────────────
0x0d     82                                                  Name = "content-type"  (indexed, table[2], 0x80|2)
0x0e     00 09                                               Value length = 9
0x10     74 65 78 74 2f 68 74 6d 6c                          Value = "text/html"
                    ── header 2 ──────────────────────────────────────────────────────────────────────
0x19     83                                                  Name = "content-length"  (indexed, table[3], 0x80|3)
0x1a     00 02                                               Value length = 2
0x1c     32 34                                               Value = "24"
                    ── header 3 ──────────────────────────────────────────────────────────────────────
0x1e     88                                                  Name = "server"  (indexed, table[8], 0x80|8)
0x1f     00 0a                                               Value length = 10
0x21     62 73 65 72 76 65 2f 31 2e 30                       Value = "bserve/1.0"
                    ── header 4 ──────────────────────────────────────────────────────────────────────
0x2b     89                                                  Name = "date"  (indexed, table[9], 0x80|9)
0x2c     00 1d                                               Value length = 29
0x2e     57 65 64 2c 20 30 37 20 4f 63 74 20 32 30 32 36    Value = "Wed, 07 Oct 2026" ...
0x3e     20 31 34 3a 33 30 3a 30 30 20 47 4d 54              "  14:30:00 GMT"
                    ── body ──────────────────────────────────────────────────────────────────────────
0x4b     3c 68 31 3e 48 65 6c 6c 6f 2c 20 62 73 65 72 76    "<h1>Hello, bserv"
0x5b     65 21 3c 2f 68 31 3e 0a                             "e!</h1>\n"
                    └───────────────────────────────────────────────────────────────────────────────────┘
```

**Raw bytes (99 bytes):**
```
0000  00 00 5a 01 05 00 00 00  01 00 c8 00 04 82 00 09  ..Z.............
0010  74 65 78 74 2f 68 74 6d  6c 83 00 02 32 34 88 00  text/html...24..
0020  0a 62 73 65 72 76 65 2f  31 2e 30 89 00 1d 57 65  .bserve/1.0...We
0030  64 2c 20 30 37 20 4f 63  74 20 32 30 32 36 20 31  d, 07 Oct 2026 1
0040  34 3a 33 30 3a 30 30 20  47 4d 54 3c 68 31 3e 48  4:30:00 GMT<h1>H
0050  65 6c 6c 6f 2c 20 62 73  65 72 76 65 21 3c 2f 68  ello, bserve!</h
0060  31 3e 0a                                           1>.
```

---

## Reading guide

- The first 3 bytes of every frame are the payload length. A receiver reads this, allocates a buffer of that size, reads exactly that many bytes, then processes or discards them based on the type byte at offset 3. This is the mechanism that allows unknown frame types to be safely skipped.
- Header names encoded with `0x80 | index` are 1 byte on the wire instead of their full string length (e.g. `content-length` saves 12 bytes per header).
- The body begins immediately after the last header; there is no separator. The receiver knows where the body starts because it has decoded all `HC` headers and the offset into the payload is then known.
