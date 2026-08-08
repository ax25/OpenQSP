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
| `0x04` | `GET_BULLETIN` | Request one complete bulletin by sequence. |

### Node responses

| Code | Name | Purpose |
|-----:|------|---------|
| `0x40` | `MESSAGE` | Return one complete private message. |
| `0x41` | `BULLETIN_HEADER` | Return one bulletin header. |
| `0x42` | `BULLETIN` | Return one complete bulletin. |
| `0x43` | `END` | Finish a multi-item response and provide the next synchronization point. |
| `0x44` | `STORED` | Confirm that a submitted message committed durably. |
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

### 5.3 Sequences

Message mailbox sequences and bulletin sequences are non-zero unsigned 32-bit values.
They are scoped as described in section 6 and are assigned by the node, not the client.

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

## 6. Persistent references and synchronization sequences

### 6.1 Message mailbox sequences

The node assigns each accepted message the next unsigned 32-bit sequence in the recipient's
mailbox. A message is identified by `(recipient, sequence)`. The authenticated mailbox is
therefore part of the meaning of both a message sequence and a message synchronization cursor.
Different mailboxes may contain the same sequence number.

### 6.2 Bulletin sequences

The node assigns bulletins from one node-local monotonically increasing unsigned 32-bit
sequence space. This single value is both the synchronization position and the persistent
bulletin reference.

In a request, the unsigned 32-bit value `since = 0` means that the client has no previous
synchronization point. A node returns visible objects whose sequence is greater than `since`.

The exact storage, filtering and cursor rules are defined in `08-node-storage.md`.

---

## 7. SEND_MESSAGE

`SEND_MESSAGE` submits one private message.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 4 | `created_at` |
| 2 | 1 | `recipient_length` |
| 3 | variable | `recipient` |
| 4 | 1 | `body_length` |
| 5 | variable | `body` |

The message author is the authenticated or transport-verified OpenQSP user. The client must not supply a separate author field.

Validation requirements:

- `created_at` is non-zero;
- `recipient` is a valid normalized callsign;
- `body` is valid UTF-8 between 1 and 208 bytes;
- the payload contains no additional bytes.

`SEND_MESSAGE` contains neither an author nor a transport transaction identifier. The author
comes only from authenticated or verified context. The node atomically stores the message and
assigns the next sequence in the recipient mailbox. Invalid, rejected or failed requests use
the normal `ERROR` operation.

Removing the former 8-byte client-generated identifier saves 8 payload bytes from every
`SEND_MESSAGE` request.

---

## 8. GET_NEW_MESSAGES

`GET_NEW_MESSAGES` requests complete private messages newer than the client's mailbox synchronization point.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 4 | `since` |
| 2 | 1 | `max` |

The payload length must be exactly 5 bytes, saving 4 bytes from the former 64-bit cursor layout.

`max` must be between `1` and `20`. The node may return fewer items because of availability, policy or transport limits.

A `since` value greater than the current message sequence produces `ERROR / INVALID_CURSOR`.

The node responds with zero or more `MESSAGE` frames followed by exactly one `END` frame.

---

## 9. MESSAGE

`MESSAGE` returns one complete private message.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 4 | `sequence` |
| 2 | 4 | `created_at` |
| 3 | 1 | `author_length` |
| 4 | variable | `author` |
| 5 | 1 | `recipient_length` |
| 6 | variable | `recipient` |
| 7 | 1 | `body_length` |
| 8 | variable | `body` |

Validation requirements:

- `sequence` and `created_at` are non-zero;
- `author` and `recipient` are valid normalized callsigns;
- `body` is valid UTF-8 between 1 and 208 bytes;
- the payload contains no additional bytes.

Private messages have no title, subject, conversation identifier or thread identifier.
Compared with the former 64-bit sequence plus 64-bit identifier layout, this saves 12 bytes
from every `MESSAGE` payload.

Receiving a `MESSAGE` does not mean that the user has read it. Read receipts and synchronized read state are outside version 0.1.

The same frame may be sent proactively while transport policy considers the
user active. A proactive frame sets the common-header `UNSOLICITED` flag
(`0x01`); a `MESSAGE` returned by `GET_NEW_MESSAGES` leaves flags at `0x00`.
This distinction is required because proactive delivery may be interleaved with
a retrieval response. It does not change sequence or synchronization semantics.

---

## 10. GET_NEW_BULLETINS

`GET_NEW_BULLETINS` requests bulletin headers newer than the client's bulletin synchronization point.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 4 | `since` |
| 2 | 1 | `max` |

The payload length must be exactly 5 bytes, saving 4 bytes from the former 64-bit cursor layout.

`max` must be between `1` and `20`.

A `since` value greater than the current bulletin sequence produces `ERROR / INVALID_CURSOR`.

The node responds with zero or more `BULLETIN_HEADER` frames followed by exactly one `END` frame.

---

## 11. BULLETIN_HEADER

`BULLETIN_HEADER` returns the compact information needed to decide whether to download a bulletin.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 4 | `sequence` |
| 2 | 4 | `created_at` |
| 3 | 1 | `author_length` |
| 4 | variable | `author` |
| 5 | 1 | `title_length` |
| 6 | variable | `title` |

Validation requirements:

- `sequence` and `created_at` are non-zero;
- `author` is a valid normalized callsign;
- `title` is valid UTF-8 between 1 and 64 bytes;
- the payload contains no additional bytes.

The title is mandatory because a sequence alone is not useful to the user. Using one 32-bit
sequence instead of separate 64-bit sequence and identifier fields saves 12 payload bytes.

The same frame may be sent proactively while transport policy considers the
user active. A proactive frame sets the common-header `UNSOLICITED` flag
(`0x01`); a header returned by `GET_NEW_BULLETINS` leaves flags at `0x00`.

---

## 12. GET_BULLETIN

`GET_BULLETIN` requests one complete bulletin.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 4 | `sequence` |

The payload length must be exactly 4 bytes and `sequence` must be non-zero. This saves 4 bytes
from the former 64-bit bulletin-reference layout.

The node responds with one `BULLETIN` frame or one `ERROR` frame. This operation does not use `END`.

---

## 13. BULLETIN

`BULLETIN` returns one complete public bulletin.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 4 | `sequence` |
| 2 | 4 | `created_at` |
| 3 | 1 | `author_length` |
| 4 | variable | `author` |
| 5 | 1 | `title_length` |
| 6 | variable | `title` |
| 7 | 1 | `body_length` |
| 8 | variable | `body` |

Validation requirements:

- `sequence` and `created_at` are non-zero;
- `author` is a valid normalized callsign;
- `title` is valid UTF-8 between 1 and 64 bytes;
- `body` is valid UTF-8 between 1 and 164 bytes;
- the payload contains no additional bytes.

A bulletin has no recipient. Its title is mandatory.
Replacing the former 64-bit identifier with the 32-bit bulletin sequence saves 4 payload bytes.

---

## 14. END

`END` terminates a response to `GET_NEW_MESSAGES` or `GET_NEW_BULLETINS`.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 1 | `request_operation` |
| 2 | 1 | `returned_count` |
| 3 | 4 | `next_since` |
| 4 | 1 | `has_more` |

The payload length must be exactly 7 bytes, saving 4 bytes from the former 64-bit cursor layout.

Validation requirements:

- `request_operation` is `GET_NEW_MESSAGES` or `GET_NEW_BULLETINS`;
- `returned_count` is between `0` and the request's `max`;
- `has_more` is `0x00` or `0x01`;
- if `returned_count` is zero, `next_since` equals the request's original `since`;
- if items were returned, `next_since` equals the sequence of the final returned item.

`has_more` values are:

| Value | Meaning |
|------:|---------|
| `0x00` | No additional visible item was known to be available when the response was generated. |
| `0x01` | Additional visible items remain and the client should repeat the request using `next_since`. |

A client must only advance its stored synchronization point after receiving and validating the corresponding `END` frame.

---

## 15. STORED

`STORED` is the payload-free durable application result for `SEND_MESSAGE`. It means that the
operation committed durably, including mailbox-sequence allocation and message insertion.
It carries no message identifier. A node must not return it before the transaction defined in
`08-node-storage.md` has committed durably.

Failures, including validation and policy rejection, use the normal `ERROR` operation. OpenQSP
`STORED` is an application/database result. An APRS `ack<ID>` is a transport acknowledgement of
packet reception; neither result substitutes for the other. The zero-byte `STORED` payload saves
9 bytes compared with the former identifier-and-status acknowledgement payload.

---

## 16. ERROR

`ERROR` reports that a request could not be completed.

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
| `0x0B` | `REJECTED` | The request is valid but refused by node policy. |

Examples:

- unknown bulletin sequence: `ERROR / NOT_FOUND`;
- `max = 0`: `ERROR / INVALID_FIELD`;
- `since` beyond the current sequence: `ERROR / INVALID_CURSOR`;
- body length above 208 bytes: `ERROR / TOO_LARGE`;
- unknown operation: `ERROR / UNKNOWN_OPERATION`.

A node should avoid including sensitive internal details in `detail`.

---

## 17. Error response behaviour

- A rejected request produces at most one `ERROR` response.
- A failed `GET_NEW_MESSAGES` or `GET_NEW_BULLETINS` request must not be followed by `END`.
- If failure occurs after one or more item frames but before `END`, the client must discard that incomplete response and keep its previous cursor.
- `INTERNAL_ERROR` must not expose stack traces, database paths or credentials.
- A receiver must remain able to process later independent frames after rejecting one malformed frame, when transport framing makes recovery possible.

---

## 18. Reliability and idempotency

- Core does not require a global object identifier for retransmission or duplicate suppression.
- A reliable ordered transport such as TCP or WebSocket needs no additional Core retry identity.
- Unreliable transports may maintain peer-scoped transaction identifiers, retries, duplicate
  suppression and replay of a prior Core result entirely within the transport adapter.
- Transport transaction identifiers must never become persistent `Message` or `Bulletin` fields.
- Transport acknowledgements do not replace OpenQSP `STORED`, and `STORED` does not replace them.
- A client must not advance an incremental synchronization point until the matching `END` frame has been received and validated.
- Repeating an incremental request with the same `since` value is safe and may return the same objects again.

---

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
