# OpenQSP Protocol

## Purpose

This document defines the application-level operations and binary frames used by OpenQSP.

User identity and stored object semantics are defined in `06-object-model.md`.

Version 0.1 is intentionally small and supports private messages and public bulletins.

---

## 1. Binary conventions

Unless explicitly stated otherwise:

- integers are unsigned;
- multi-byte integers use network byte order (big-endian);
- text uses UTF-8;
- callsigns use normalized uppercase ASCII as defined in `06-object-model.md`;
- lengths count bytes, not characters;
- malformed or truncated frames must be rejected.

---

## 2. Common frame header

Every OpenQSP frame starts with this 4-byte header.

| Offset | Size | Field | Description |
|-------:|-----:|-------|-------------|
| 0 | 1 | `version` | Protocol version. Version 0.1 uses `0x01`. |
| 1 | 1 | `operation` | Operation code. |
| 2 | 1 | `flags` | Version 0.1 requires `0x00`. |
| 3 | 1 | `payload_length` | Number of bytes after the header. |

The maximum payload in one version 0.1 Core frame is 255 bytes.

---

## 3. Operations

| Code | Name | Purpose |
|-----:|------|---------|
| `0x01` | `SEND_MESSAGE` | Submit one private message for durable storage. |
| `0x02` | `GET_MESSAGES` | Request pending private messages for the authenticated user. |
| `0x03` | `MESSAGE` | Deliver one private message. |
| `0x04` | `POST_BULLETIN` | Submit one public bulletin. |
| `0x05` | `GET_BULLETIN_HEADERS` | Request a compact list of bulletin identifiers and titles. |
| `0x06` | `GET_BULLETIN` | Request one bulletin by identifier. |
| `0x07` | `BULLETIN` | Deliver one complete bulletin. |
| `0x08` | `ACK_OBJECT` | Report the durable processing result for one submitted object. |

Unknown operation codes must be rejected in version 0.1.

---

## 4. SEND_MESSAGE

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 8 | `object_id` |
| 2 | 4 | `created_at` |
| 3 | 1 | `author_length` |
| 4 | variable | `author` |
| 5 | 1 | `recipient_length` |
| 6 | variable | `recipient` |
| 7 | 1 | `body_length` |
| 8 | variable | `body` |

The sender generates the 64-bit `object_id` before the first transmission. Retries of the same message must reuse the same identifier and identical content.

A receiver must process duplicates idempotently. If the same identifier is received with different content, it must be rejected as a conflict.

---

## 5. GET_MESSAGES

`GET_MESSAGES` requests private messages currently available for the authenticated user.

Version 0.1 defines an empty payload.

The server responds with zero or more `MESSAGE` frames. Delivery selection, pending state and retry policy are implementation details unless later specified.

---

## 6. MESSAGE

`MESSAGE` uses the same object payload as `SEND_MESSAGE`.

Receiving a `MESSAGE` does not imply that the user has read it. Read receipts and synchronized read state are not defined in version 0.1.

---

## 7. POST_BULLETIN

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 8 | `object_id` |
| 2 | 4 | `created_at` |
| 3 | 1 | `author_length` |
| 4 | variable | `author` |
| 5 | 1 | `title_length` |
| 6 | variable | `title` |
| 7 | 1 | `body_length` |
| 8 | variable | `body` |

Bulletins are public objects and do not contain a recipient.

---

## 8. GET_BULLETIN_HEADERS

Requests a compact list of available bulletin headers.

The exact pagination and range fields are deferred until the first implementation proves what is necessary.

A header contains at least:

- `object_id`;
- `created_at`;
- `author`;
- `title`.

---

## 9. GET_BULLETIN

Requests one bulletin by its 64-bit `object_id`.

The payload contains only that identifier.

The server responds with `BULLETIN` or an error response to be defined.

---

## 10. BULLETIN

`BULLETIN` uses the same object payload as `POST_BULLETIN`.

---

## 11. ACK_OBJECT

`ACK_OBJECT` confirms the durable processing result of `SEND_MESSAGE` or `POST_BULLETIN`.

It is an application acknowledgement, not a transport acknowledgement.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 8 | `object_id` |
| 2 | 1 | `status` |

Status codes:

| Code | Name | Meaning |
|-----:|------|---------|
| `0x00` | `STORED` | Object durably stored. |
| `0x01` | `ALREADY_STORED` | Identical object already stored. |
| `0x02` | `REJECTED` | Parsed but refused. |
| `0x03` | `INVALID` | Malformed frame or object. |
| `0x04` | `CONFLICT` | Identifier exists with different content. |

Only `STORED` and `ALREADY_STORED` complete successful delivery to the receiving node.

---

## 12. Reliability

- Clients must persist submitted objects before transmission.
- Retries must reuse the original identifier and exact content.
- Receivers must process duplicate submissions idempotently.
- `STORED` must only be returned after durable storage.
