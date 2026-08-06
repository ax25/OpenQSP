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
| 2 | 1 | `flags` | Version 0.1 requires `0x00`. |
| 3 | 1 | `payload_length` | Number of bytes after the header. |

The maximum payload of one version 0.1 Core frame is 255 bytes. The maximum complete Core-frame size is therefore 259 bytes.

Transport adapters may fragment and reassemble a Core frame when required, but must deliver the original complete frame without changing its application meaning.

### 2.1 Header validation

A receiver must reject a frame when:

- `version` is not `0x01`;
- `operation` is unknown for version 0.1;
- `flags` is not `0x00`;
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
| `0x44` | `ACK` | Report the durable processing result of a submitted object. |
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

### 5.3 Identifiers

`message_id` and `bulletin_id` must be non-zero unsigned 64-bit values.

Object identifiers are unique across object types within one node, as defined in `08-node-storage.md`.

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

## 6. Identifiers and synchronization sequences

### 6.1 Object identifiers

Messages and bulletins use client-generated or publisher-generated unsigned 64-bit object identifiers.

An object identifier remains stable across retries and transports. Reusing an existing identifier with different immutable content is a conflict.

### 6.2 Node sequences

For incremental retrieval, a node assigns independent monotonically increasing unsigned 64-bit sequences to:

- the node's private-message stream;
- the node's public bulletin stream.

A sequence is a node-local synchronization cursor. It is not the object identifier and is not required to be globally unique.

In a request, `since = 0` means that the client has no previous synchronization point. A node returns visible objects whose sequence is greater than `since`.

The exact storage, filtering and cursor rules are defined in `08-node-storage.md`.

---

## 7. SEND_MESSAGE

`SEND_MESSAGE` submits one private message.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 8 | `message_id` |
| 2 | 4 | `created_at` |
| 3 | 1 | `recipient_length` |
| 4 | variable | `recipient` |
| 5 | 1 | `body_length` |
| 6 | variable | `body` |

The message author is the authenticated or transport-verified OpenQSP user. The client must not supply a separate author field.

Validation requirements:

- `message_id` is non-zero;
- `created_at` is non-zero;
- `recipient` is a valid normalized callsign;
- `body` is valid UTF-8 between 1 and 208 bytes;
- the payload contains no additional bytes.

The sender must persist the message before first transmission. Every retry must reuse the same `message_id`, recipient, timestamp and body.

If the node can recover `message_id`, object validation and storage results use `ACK`. A frame too malformed to recover the identifier uses `ERROR` when a response is possible.

---

## 8. GET_NEW_MESSAGES

`GET_NEW_MESSAGES` requests complete private messages newer than the client's mailbox synchronization point.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 8 | `since` |
| 2 | 1 | `max` |

The payload length must be exactly 9 bytes.

`max` must be between `1` and `20`. The node may return fewer items because of availability, policy or transport limits.

A `since` value greater than the current message sequence produces `ERROR / INVALID_CURSOR`.

The node responds with zero or more `MESSAGE` frames followed by exactly one `END` frame.

---

## 9. MESSAGE

`MESSAGE` returns one complete private message.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 8 | `sequence` |
| 2 | 8 | `message_id` |
| 3 | 4 | `created_at` |
| 4 | 1 | `author_length` |
| 5 | variable | `author` |
| 6 | 1 | `recipient_length` |
| 7 | variable | `recipient` |
| 8 | 1 | `body_length` |
| 9 | variable | `body` |

Validation requirements:

- `sequence`, `message_id` and `created_at` are non-zero;
- `author` and `recipient` are valid normalized callsigns;
- `body` is valid UTF-8 between 1 and 208 bytes;
- the payload contains no additional bytes.

Private messages have no title, subject, conversation identifier or thread identifier.

Receiving a `MESSAGE` does not mean that the user has read it. Read receipts and synchronized read state are outside version 0.1.

The same frame may be sent proactively while transport policy considers the user active. Proactive delivery does not change sequence or synchronization semantics.

---

## 10. GET_NEW_BULLETINS

`GET_NEW_BULLETINS` requests bulletin headers newer than the client's bulletin synchronization point.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 8 | `since` |
| 2 | 1 | `max` |

The payload length must be exactly 9 bytes.

`max` must be between `1` and `20`.

A `since` value greater than the current bulletin sequence produces `ERROR / INVALID_CURSOR`.

The node responds with zero or more `BULLETIN_HEADER` frames followed by exactly one `END` frame.

---

## 11. BULLETIN_HEADER

`BULLETIN_HEADER` returns the compact information needed to decide whether to download a bulletin.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 8 | `sequence` |
| 2 | 8 | `bulletin_id` |
| 3 | 4 | `created_at` |
| 4 | 1 | `author_length` |
| 5 | variable | `author` |
| 6 | 1 | `title_length` |
| 7 | variable | `title` |

Validation requirements:

- `sequence`, `bulletin_id` and `created_at` are non-zero;
- `author` is a valid normalized callsign;
- `title` is valid UTF-8 between 1 and 64 bytes;
- the payload contains no additional bytes.

The title is mandatory because an identifier alone is not useful to the user.

The same frame may be sent proactively while transport policy considers the user active.

---

## 12. GET_BULLETIN

`GET_BULLETIN` requests one complete bulletin.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 8 | `bulletin_id` |

The payload length must be exactly 8 bytes and `bulletin_id` must be non-zero.

The node responds with one `BULLETIN` frame or one `ERROR` frame. This operation does not use `END`.

---

## 13. BULLETIN

`BULLETIN` returns one complete public bulletin.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 8 | `bulletin_id` |
| 2 | 4 | `created_at` |
| 3 | 1 | `author_length` |
| 4 | variable | `author` |
| 5 | 1 | `title_length` |
| 6 | variable | `title` |
| 7 | 1 | `body_length` |
| 8 | variable | `body` |

Validation requirements:

- `bulletin_id` and `created_at` are non-zero;
- `author` is a valid normalized callsign;
- `title` is valid UTF-8 between 1 and 64 bytes;
- `body` is valid UTF-8 between 1 and 164 bytes;
- the payload contains no additional bytes.

A bulletin has no recipient. Its title is mandatory.

---

## 14. END

`END` terminates a response to `GET_NEW_MESSAGES` or `GET_NEW_BULLETINS`.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 1 | `request_operation` |
| 2 | 1 | `returned_count` |
| 3 | 8 | `next_since` |
| 4 | 1 | `has_more` |

The payload length must be exactly 11 bytes.

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

## 15. ACK

`ACK` reports the durable processing result of `SEND_MESSAGE`.

It is an application acknowledgement, not a transport acknowledgement.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 8 | `object_id` |
| 2 | 1 | `status` |

The payload length must be exactly 9 bytes and `object_id` must be non-zero.

Status codes:

| Code | Name | Meaning |
|-----:|------|---------|
| `0x00` | `STORED` | The object was durably stored. |
| `0x01` | `ALREADY_STORED` | The identical object was already stored. |
| `0x02` | `REJECTED` | The object was structurally valid but refused by node policy. |
| `0x03` | `INVALID` | The object fields or content failed validation. |
| `0x04` | `CONFLICT` | The identifier already exists with a different object type or immutable content. |

Only `STORED` and `ALREADY_STORED` complete successful submission.

A node must not return `STORED` before the transaction defined in `08-node-storage.md` has committed durably.

### 15.1 ACK versus ERROR

For `SEND_MESSAGE`:

- use `ACK / INVALID` when `message_id` was parsed but another object field is invalid;
- use `ACK / REJECTED` when the complete object is valid but policy refuses it;
- use `ACK / CONFLICT` when the identifier collides with different immutable content;
- use `ERROR` when the frame cannot be parsed sufficiently to identify the object or when request processing fails outside object acceptance.

---

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
- body length above 208 bytes: `ACK / INVALID` when `message_id` is available, otherwise `ERROR / TOO_LARGE`;
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

## 18. Reliability and idempotency

- Clients must persist submitted messages before transmission.
- Retries must reuse the original identifier and exact immutable content.
- Nodes must process duplicate submissions idempotently.
- An identifier reused with different content must produce `ACK / CONFLICT`.
- Transport acknowledgements do not replace `ACK / STORED` or `ACK / ALREADY_STORED`.
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
