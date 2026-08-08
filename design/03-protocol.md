# OpenQSP Protocol

## Purpose

This document defines the binary representation of the logical client/node operations specified in `07-client-node-protocol.md`.

User identity and stored object semantics are defined in `06-object-model.md`. Transport framing, fragmentation, retries and activity behaviour are defined in `04-transports.md`. Persistent cursor and durability rules are defined in `08-node-storage.md`.

OpenQSP version 0.1 supports private messages and public bulletin retrieval. Bulletin publication is not yet assigned a version 0.1 client operation.

---

## 1. Binary conventions

Unless explicitly stated otherwise:

- integers are unsigned;
- multi-byte integers use network byte order (big-endian);
- text uses UTF-8;
- callsigns use normalized uppercase ASCII as defined in `06-object-model.md`;
- lengths count bytes, not characters;
- timestamps are unsigned 32-bit Unix timestamps in UTC;
- malformed, oversized or truncated frames must be rejected;
- fields must consume the payload exactly: trailing or missing bytes are invalid.

---

## 2. Common frame header

Every OpenQSP Core frame starts with this 4-byte header.

| Offset | Size | Field | Description |
|-------:|-----:|-------|-------------|
| 0 | 1 | `version` | Protocol version. Version 0.1 uses `0x01`. |
| 1 | 1 | `operation` | Operation code. |
| 2 | 1 | `flags` | `0x00`, or `0x01` for an unsolicited node delivery. |
| 3 | 1 | `payload_length` | Number of bytes after the header. |

The maximum payload of one version 0.1 Core frame is 255 bytes. The maximum complete Core-frame size is therefore 259 bytes.

Transport adapters may fragment and reassemble a Core frame when required, but must deliver the original complete frame without changing its application meaning.

### 2.1 Header validation

A receiver must reject a frame when:

- `version` is not `0x01`;
- `operation` is unknown for version 0.1;
- an undefined flag bit is set;
- `UNSOLICITED` (`0x01`) is set on an operation other than `MESSAGE` or
  `BULLETIN_HEADER`;
- the actual payload size differs from `payload_length`;
- the complete frame is truncated or contains bytes beyond the declared payload.

When the request header is sufficiently readable, the node should return an `ERROR` response. A transport may silently discard data that is too incomplete to identify a valid OpenQSP request.

---

## 3. Operation codes

### Client requests

| Code | Name | Purpose |
|-----:|------|---------|
| `0x01` | `SEND_MESSAGE` | Submit one private message for durable storage. |
| `0x02` | `GET_NEW_MESSAGES` | Request complete private messages after a synchronization point. |
| `0x03` | `GET_NEW_BULLETINS` | Request bulletin headers after a synchronization point. |
| `0x04` | `GET_BULLETIN` | Request one complete bulletin by identifier. |

### Node responses

| Code | Name | Purpose |
|-----:|------|---------|
| `0x40` | `MESSAGE` | Return one complete private message. |
| `0x41` | `BULLETIN_HEADER` | Return one bulletin header. |
| `0x42` | `BULLETIN` | Return one complete bulletin. |
| `0x43` | `END` | Finish a multi-item response and provide the next synchronization point. |
| `0x44` | `STORED` | Confirm durable storage of a submitted message. |
| `0x45` | `ERROR` | Report that a request could not be completed. |

Unknown operation codes must produce `ERROR / UNKNOWN_OPERATION` when a response is possible.

---

## 4. Version 0.1 limits

All limits are expressed in encoded bytes.

| Field or value | Minimum | Maximum |
|---|---:|---:|
| Normalized callsign | 3 | 12 |
| Private-message body | 1 | 208 |
| Bulletin title | 1 | 64 |
| Bulletin body | 1 | 164 |
| Retrieval `max` | 1 | 20 |
| `ERROR.detail` | 0 | 64 |

These limits ensure that every version 0.1 application object fits inside one 255-byte Core-frame payload, including the largest `MESSAGE` and `BULLETIN` response layouts.

A sender must validate limits before transmission. A node must independently enforce them.

Version 0.1 does not define multi-frame application objects. Transport fragmentation may split one Core frame for carriage but cannot be used to exceed these application limits.

---

## 5. General validation rules

### 5.1 Callsigns

Every callsign field must:

- contain between 3 and 12 ASCII bytes;
- already be normalized to uppercase base-callsign form;
- contain only `A` through `Z` and `0` through `9`;
- contain at least one letter and at least one digit;
- contain no SSID, `/P`, `/M`, whitespace or punctuation.

The protocol does not attempt to validate every national callsign allocation rule. It validates only the normalized OpenQSP form.

### 5.2 Text

Every text field must:

- contain valid UTF-8;
- respect its byte limit;
- contain no NUL byte (`0x00`).

Message bodies, bulletin titles and bulletin bodies must not be empty in version 0.1.

Text is compared by exact encoded bytes after successful UTF-8 validation. Version 0.1 performs no Unicode normalization, whitespace rewriting or case folding on message or bulletin text.

### 5.3 Sequences and cursors

Message mailbox sequences and bulletin sequences are unsigned 32-bit values.
Object sequences are non-zero; synchronization cursor zero means no prior
position. Private-message identity is scoped as `(recipient, sequence)` and a
bulletin's node-local sequence is its sole reference.

### 5.4 Timestamps

`created_at` must be non-zero.

A node may reject a timestamp that is implausibly far in the future according to local policy, but version 0.1 does not prescribe a fixed clock-skew window. A node must not rewrite the accepted creator timestamp.

### 5.5 Length fields

Each one-byte length field must equal the exact number of bytes occupied by the following field.

A zero length is invalid for callsigns, message bodies, bulletin titles and bulletin bodies. It is valid only for optional `ERROR.detail`.

### 5.6 Authorization context

Every client request requires an authenticated or transport-verified OpenQSP user.

The author of a submitted message is taken exclusively from this context. An application object must never override the authenticated author.

---

## 6. Application identity, cursors, and transport identifiers

OpenQSP separates persistent application objects, synchronization cursors, and
transport reliability identifiers. Each recipient mailbox has an independent,
monotonically increasing u32 sequence. Bulletin sequences are monotonically
increasing u32 values within a node. Transport-envelope identifiers used by an
unreliable adapter are neither application fields nor synchronization cursors.

## 7. SEND_MESSAGE

Payload, in order:

| Order | Size | Field |
|---:|---:|---|
| 1 | 4 | `created_at` |
| 2 | 1 | `recipient_length` |
| 3 | variable | UTF-8 `recipient` |
| 4 | 1 | `body_length` |
| 5 | variable | UTF-8 `body` |

The author comes exclusively from authenticated context. The node validates all
fields, atomically allocates the recipient mailbox's next sequence, commits the
message durably, and returns `STORED`. Failures return `ERROR`.

## 8. GET_NEW_MESSAGES

Payload is `since:u32, max:u8` (exactly 5 bytes). It returns messages in the
authenticated user's mailbox whose mailbox sequence is greater than `since`,
in ascending order, followed by `END`. A cursor ahead of that mailbox's
persistent high-water mark is `ERROR / INVALID_CURSOR`.

## 9. MESSAGE

Payload is `sequence:u32, created_at:u32`, followed by one-byte-length-prefixed
`author`, `recipient`, and `body`. Sequence and timestamp are non-zero and all
callsign/text validation rules apply. The sequence is meaningful only together
with the recipient mailbox.

## 10. GET_NEW_BULLETINS

Payload is `since:u32, max:u8` (exactly 5 bytes). Headers with sequence greater
than `since` are returned in ascending order, followed by `END`.

## 11. BULLETIN_HEADER

Payload is `sequence:u32, created_at:u32`, followed by one-byte-length-prefixed
`author` and `title`. The node-local sequence is the bulletin reference.

## 12. GET_BULLETIN

Payload is exactly one non-zero `sequence:u32`. The response is the matching
`BULLETIN`, or `ERROR / NOT_FOUND`.

## 13. BULLETIN

Payload is `sequence:u32, created_at:u32`, followed by one-byte-length-prefixed
`author`, `title`, and `body`.

## 14. END

Payload is exactly 7 bytes: `request_operation:u8, returned_count:u8,
next_since:u32, has_more:u8`. The request operation must be one of the two
incremental retrieval operations. `has_more` is zero or one. `next_since` is
the last returned sequence, or the requested cursor when no item was returned.

## 15. STORED

Operation `0x44` has a zero-length payload. It is returned only after a
`SEND_MESSAGE` storage transaction commits durably. It is not a transport ACK
and carries no application identifier.

## 16. ERROR

`ERROR` reports failure of a request that is not represented by an object-processing `ACK`.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 1 | `request_operation` |
| 2 | 1 | `error_code` |
| 3 | 1 | `detail_length` |
| 4 | variable | `detail` |

`detail` is optional human-readable UTF-8 text between 0 and 64 bytes. Clients must make decisions from `error_code`, not by parsing `detail`.

If the request operation cannot be determined, `request_operation` must be `0x00`.

Error codes:

| Code | Name | Meaning |
|-----:|------|---------|
| `0x01` | `INVALID_FRAME` | Header, payload length, framing or field layout is malformed. |
| `0x02` | `UNSUPPORTED_VERSION` | The frame version is not supported. |
| `0x03` | `UNKNOWN_OPERATION` | The operation code is unknown for the requested version. |
| `0x04` | `INVALID_FIELD` | A request parameter or field value is invalid. |
| `0x05` | `INVALID_CURSOR` | `since` is not valid for the current node sequence state. |
| `0x06` | `UNAUTHORIZED` | The user is not authenticated or not permitted. |
| `0x07` | `NOT_FOUND` | The requested object does not exist or is not visible to the user. |
| `0x08` | `TOO_LARGE` | A declared or decoded field exceeds a version 0.1 limit. |
| `0x09` | `BUSY` | The node cannot process the request temporarily. |
| `0x0A` | `INTERNAL_ERROR` | The node failed while processing an otherwise valid request. |

Examples:

- unknown bulletin identifier: `ERROR / NOT_FOUND`;
- `max = 0`: `ERROR / INVALID_FIELD`;
- `since` beyond the current sequence: `ERROR / INVALID_CURSOR`;
- body length above 208 bytes: `ERROR / TOO_LARGE`;
- unknown operation: `ERROR / UNKNOWN_OPERATION`.

A node should avoid including sensitive internal details in `detail`.

---

## 17. Error response behaviour

- A rejected request produces at most one `ACK` or one `ERROR` response.
- A failed `GET_NEW_MESSAGES` or `GET_NEW_BULLETINS` request must not be followed by `END`.
- If failure occurs after one or more item frames but before `END`, the client must discard that incomplete response and keep its previous cursor.
- `INTERNAL_ERROR` must not expose stack traces, database paths or credentials.
- A receiver must remain able to process later independent frames after rejecting one malformed frame, when transport framing makes recovery possible.

---

## 18. Reliability boundary

TCP and WebSocket rely on their reliable ordered transport. An unreliable
adapter such as APRS may add peer-scoped transaction IDs, transport ACKs,
retries, duplicate suppression, and replay of a cached Core result in its
transport envelope. Those identifiers never become Message or Bulletin fields.
`APRS ack<ID>` means a transport packet was received; OpenQSP `STORED` means an
application transaction committed durably.

## 19. Deferred protocol details

The following remain outside version 0.1 or require a later extension:

- bulletin publication;
- application objects larger than one Core-frame payload;
- attachments and files;
- message deletion or editing;
- read receipts;
- groups and conversations;
- federation and node-to-node synchronization;
- cryptographic signatures and end-to-end encryption;
- a richer international callsign grammar;
- Unicode normalization rules.
