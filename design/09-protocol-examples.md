# 09 - Protocol Examples and Test Vectors

## Purpose

This document provides canonical binary examples for OpenQSP version 0.1.

The vectors are intended to be copied directly into parser, encoder and integration tests. The binary layouts are defined in `03-protocol.md`; logical behaviour is defined in `07-client-node-protocol.md`.

Unless stated otherwise:

- hexadecimal bytes are separated by spaces;
- multi-byte integers use big-endian order;
- text is UTF-8;
- frame bytes include the 4-byte Core header;
- every request/response example uses protocol version `0x01` and flags
  `0x00`; proactive `MESSAGE` and `BULLETIN_HEADER` deliveries use the
  `UNSOLICITED` flag `0x01`.

---

## 1. Common example values

| Name | Value |
|---|---|
| Message mailbox sequence | `125` (`0x0000007D`) |
| Bulletin sequence | `246` (`0x000000F6`) |
| `created_at` | `0x65000000` |
| Message author | `EA3GNU` |
| Message recipient | `EA1ABC` |
| Message body | `Hola` |
| Bulletin author | `EA1ABC` |
| Bulletin title | `Test VHF` |
| Bulletin body | `Actividad domingo` |

---

## 2. SEND_MESSAGE

Logical fields:

```text
created_at = 0x65000000
recipient  = EA1ABC
body       = Hola
```

Payload length: `16` bytes (`0x10`).

```hex
01 01 00 10
65 00 00 00
06 45 41 31 41 42 43
04 48 6F 6C 61
```

Complete frame:

```hex
01 01 00 10 65 00 00 00 06 45 41 31 41 42 43 04 48 6F 6C 61
```

Expected result for a new object:

```text
STORED
```

The byte-identical request has no Core retry identity. A reliable transport sends it once;
an unreliable transport is responsible for suppressing duplicate transactions or replaying
the prior result before another Core submission.

---

## 3. STORED

`STORED` has no payload.

```hex
01 44 00 00
```

Complete frame:

```hex
01 44 00 00
```

---

## 4. GET_NEW_MESSAGES

Logical fields:

```text
since = 124
max   = 5
```

Payload length: `5` bytes (`0x05`).

```hex
01 02 00 05
00 00 00 7C
05
```

Complete frame:

```hex
01 02 00 05 00 00 00 7C 05
```

---

## 5. MESSAGE

Logical fields:

```text
sequence   = 125 (in EA1ABC's mailbox)
created_at = 0x65000000
author     = EA3GNU
recipient  = EA1ABC
body       = Hola
```

Payload length: `27` bytes (`0x1B`).

```hex
01 40 00 1B
00 00 00 7D
65 00 00 00
06 45 41 33 47 4E 55
06 45 41 31 41 42 43
04 48 6F 6C 61
```

Complete frame:

```hex
01 40 00 1B 00 00 00 7D 65 00 00 00 06 45 41 33 47 4E 55 06 45 41 31 41 42 43 04 48 6F 6C 61
```

---

## 6. END for GET_NEW_MESSAGES

Logical fields:

```text
request_operation = GET_NEW_MESSAGES (0x02)
returned_count    = 1
next_since        = 125
has_more          = false
```

Payload length: `7` bytes (`0x07`).

```hex
01 43 00 07
02
01
00 00 00 7D
00
```

Complete frame:

```hex
01 43 00 07 02 01 00 00 00 7D 00
```

---

## 7. GET_NEW_BULLETINS

Logical fields:

```text
since = 245
max   = 5
```

Payload length: `5` bytes (`0x05`).

```hex
01 03 00 05
00 00 00 F5
05
```

Complete frame:

```hex
01 03 00 05 00 00 00 F5 05
```

---

## 8. BULLETIN_HEADER

Logical fields:

```text
sequence    = 246
created_at  = 0x65000000
author      = EA1ABC
title       = Test VHF
```

Payload length: `24` bytes (`0x18`).

```hex
01 41 00 18
00 00 00 F6
65 00 00 00
06 45 41 31 41 42 43
08 54 65 73 74 20 56 48 46
```

Complete frame:

```hex
01 41 00 18 00 00 00 F6 65 00 00 00 06 45 41 31 41 42 43 08 54 65 73 74 20 56 48 46
```

---

## 9. END for GET_NEW_BULLETINS

Logical fields:

```text
request_operation = GET_NEW_BULLETINS (0x03)
returned_count    = 1
next_since        = 246
has_more          = false
```

Payload length: `7` bytes (`0x07`).

```hex
01 43 00 07
03
01
00 00 00 F6
00
```

Complete frame:

```hex
01 43 00 07 03 01 00 00 00 F6 00
```

---

## 10. GET_BULLETIN

Logical fields:

```text
sequence = 246
```

Payload length: `4` bytes (`0x04`).

```hex
01 04 00 04
00 00 00 F6
```

Complete frame:

```hex
01 04 00 04 00 00 00 F6
```

---

## 11. BULLETIN

Logical fields:

```text
sequence    = 246
created_at  = 0x65000000
author      = EA1ABC
title       = Test VHF
body        = Actividad domingo
```

Payload length: `42` bytes (`0x2A`).

```hex
01 42 00 2A
00 00 00 F6
65 00 00 00
06 45 41 31 41 42 43
08 54 65 73 74 20 56 48 46
11 41 63 74 69 76 69 64 61 64 20 64 6F 6D 69 6E 67 6F
```

Complete frame:

```hex
01 42 00 2A 00 00 00 F6 65 00 00 00 06 45 41 31 41 42 43 08 54 65 73 74 20 56 48 46 11 41 63 74 69 76 69 64 61 64 20 64 6F 6D 69 6E 67 6F
```

---

## 12. ERROR / NOT_FOUND

Logical fields:

```text
request_operation = GET_BULLETIN (0x04)
error_code        = NOT_FOUND (0x07)
detail            = Not found
```

Payload length: `12` bytes (`0x0C`).

```hex
01 45 00 0C
04
07
09 4E 6F 74 20 66 6F 75 6E 64
```

Complete frame:

```hex
01 45 00 0C 04 07 09 4E 6F 74 20 66 6F 75 6E 64
```

Clients must make decisions from error code `0x07`, not from the detail text.

---

## 13. Empty incremental response

For this request:

```text
GET_NEW_MESSAGES since=125 max=5
```

with no newer messages, the node returns only:

```text
END
request_operation = GET_NEW_MESSAGES
returned_count    = 0
next_since        = 125
has_more          = false
```

Canonical frame:

```hex
01 43 00 07 02 00 00 00 00 7D 00
```

---

## 14. Pagination example

Assume messages with sequences `125`, `126` and `127` exist, and the client sends:

```text
GET_NEW_MESSAGES since=124 max=2
```

The first response is:

```text
MESSAGE sequence=125
MESSAGE sequence=126
END returned_count=2 next_since=126 has_more=true
```

The client then sends:

```text
GET_NEW_MESSAGES since=126 max=2
```

The second response is:

```text
MESSAGE sequence=127
END returned_count=1 next_since=127 has_more=false
```

The client must not advance from `124` to `126` until the first `END` has been received and validated.

---

## 15. Invalid test vectors

The following vectors are intentionally invalid and should be used as negative parser tests.

### 15.1 Unsupported version

```hex
02 04 00 04 00 00 00 F6
```

Expected result when a response is possible:

```text
ERROR / UNSUPPORTED_VERSION
```

### 15.2 Non-zero flags

```hex
01 04 01 04 00 00 00 F6
```

Expected result:

```text
ERROR / INVALID_FRAME
```

The frame remains invalid because `UNSOLICITED` is not permitted on
`GET_BULLETIN`. The `0x01` flag is valid only on node-originated proactive
`MESSAGE` and `BULLETIN_HEADER` frames.

### 15.3 Declared payload longer than actual payload

```hex
01 04 00 04 00 00
```

Expected result:

```text
ERROR / INVALID_FRAME
```

A transport may discard the data silently if the request cannot be identified reliably.

### 15.4 Trailing byte beyond declared payload

```hex
01 04 00 04 00 00 00 F6 FF
```

Expected result:

```text
ERROR / INVALID_FRAME
```

### 15.5 GET_NEW_MESSAGES with max zero

```hex
01 02 00 05 00 00 00 7C 00
```

Expected result:

```text
ERROR / INVALID_FIELD
```

### 15.6 SEND_MESSAGE with empty body

```hex
01 01 00 0C 65 00 00 00 06 45 41 31 41 42 43 00
```

Expected result:

```text
ERROR / INVALID_FIELD
```

### 15.7 SEND_MESSAGE with invalid recipient

The recipient contains a hyphenated APRS SSID and is not normalized:

```hex
01 01 00 13 65 00 00 00 09 45 41 31 41 42 43 2D 31 30 04 48 6F 6C 61
```

Expected result:

```text
ERROR / INVALID_FIELD
```

### 15.8 Invalid UTF-8 body

```hex
01 01 00 0E 65 00 00 00 06 45 41 31 41 42 43 02 C3 28
```

Expected result:

```text
ERROR / INVALID_FIELD
```

### 15.9 Unknown operation

```hex
01 7F 00 00
```

Expected result:

```text
ERROR / UNKNOWN_OPERATION
```

---

## 16. Required implementation tests

At minimum, implementations should use these vectors to verify:

1. Exact decoding of every canonical frame.
2. Re-encoding produces byte-for-byte identical output.
3. Big-endian integer handling.
4. Exact payload-length validation.
5. Rejection of unknown operations and unsupported versions.
6. Enforcement of callsign and text rules.
7. Payload-free `STORED` and `SEND_MESSAGE` error behaviour.
8. Incremental retrieval ordering.
9. Cursor advancement only after `END`.
10. Correct empty and paginated responses.
11. `NOT_FOUND` handling for unknown bulletins.
12. Safe rejection of truncated and malformed frames.
