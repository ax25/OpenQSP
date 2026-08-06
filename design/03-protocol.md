# OpenQSP Protocol

## Purpose

This document defines the binary representation of the logical client/node operations specified in `07-client-node-protocol.md`.

User identity and stored object semantics are defined in `06-object-model.md`. Transport framing, fragmentation, retries and activity behaviour are defined in `04-transports.md`.

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
- malformed, oversized or truncated frames must be rejected.

---

## 2. Common frame header

Every OpenQSP Core frame starts with this 4-byte header.

| Offset | Size | Field | Description |
|-------:|-----:|-------|-------------|
| 0 | 1 | `version` | Protocol version. Version 0.1 uses `0x01`. |
| 1 | 1 | `operation` | Operation code. |
| 2 | 1 | `flags` | Version 0.1 requires `0x00`. |
| 3 | 1 | `payload_length` | Number of bytes after the header. |

The maximum payload of one version 0.1 Core frame is 255 bytes.

Transport adapters may fragment and reassemble a Core frame when required, but must deliver the original complete frame without changing its application meaning.

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

Unknown operation codes must be rejected in version 0.1.

---

## 4. Identifiers and synchronization sequences

### 4.1 Object identifiers

Messages and bulletins use client-generated or publisher-generated unsigned 64-bit object identifiers.

An object identifier remains stable across retries and transports. Reusing an existing identifier with different immutable content is a conflict.

### 4.2 Node sequences

For incremental retrieval, a node assigns a monotonically increasing unsigned 64-bit sequence independently to:

- private messages in each user mailbox;
- the node's public bulletin stream.

A sequence is a node-local synchronization cursor. It is not the object identifier and is not required to be globally unique.

In a request, `since = 0` means that the client has no previous synchronization point. A node returns objects whose sequence is greater than `since`.

---

## 5. SEND_MESSAGE

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

The sender must persist the message before first transmission. Every retry must reuse the same `message_id`, recipient, timestamp and body.

The node responds with `ACK` when it can identify the submitted object. A frame that cannot be parsed sufficiently to recover `message_id` may instead produce `ERROR / INVALID`.

---

## 6. GET_NEW_MESSAGES

`GET_NEW_MESSAGES` requests complete private messages newer than the client's mailbox synchronization point.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 8 | `since` |
| 2 | 1 | `max` |

`max` must be between `1` and `255`. A node may return fewer items because of availability, policy or transport limits.

The node responds with zero or more `MESSAGE` frames followed by exactly one `END` frame.

---

## 7. MESSAGE

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

Private messages have no title, subject, conversation identifier or thread identifier.

Receiving a `MESSAGE` does not mean that the user has read it. Read receipts and synchronized read state are outside version 0.1.

The same frame may be sent proactively while transport policy considers the user active. Proactive delivery does not change sequence or synchronization semantics.

---

## 8. GET_NEW_BULLETINS

`GET_NEW_BULLETINS` requests bulletin headers newer than the client's bulletin synchronization point.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 8 | `since` |
| 2 | 1 | `max` |

`max` must be between `1` and `255`.

The node responds with zero or more `BULLETIN_HEADER` frames followed by exactly one `END` frame.

---

## 9. BULLETIN_HEADER

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

The title is mandatory and `title_length` must be greater than zero.

The same frame may be sent proactively while transport policy considers the user active.

---

## 10. GET_BULLETIN

`GET_BULLETIN` requests one complete bulletin.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 8 | `bulletin_id` |

The node responds with one `BULLETIN` frame or one `ERROR` frame. This operation does not use `END`.

---

## 11. BULLETIN

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

A bulletin has no recipient. Its title is mandatory.

---

## 12. END

`END` terminates a response to `GET_NEW_MESSAGES` or `GET_NEW_BULLETINS`.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 1 | `request_operation` |
| 2 | 1 | `returned_count` |
| 3 | 8 | `next_since` |
| 4 | 1 | `has_more` |

`request_operation` must be `GET_NEW_MESSAGES` or `GET_NEW_BULLETINS`.

`next_since` is the sequence of the last item returned. If no item was returned, it equals the request's original `since` value.

`has_more` values are:

| Value | Meaning |
|------:|---------|
| `0x00` | No additional item was known to be available when the response was generated. |
| `0x01` | Additional items remain and the client should repeat the request using `next_since`. |

A client must only advance its stored synchronization point after receiving a valid `END` frame for the corresponding response.

---

## 13. ACK

`ACK` reports the durable processing result of `SEND_MESSAGE`.

It is an application acknowledgement, not a transport acknowledgement.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 8 | `object_id` |
| 2 | 1 | `status` |

Status codes:

| Code | Name | Meaning |
|-----:|------|---------|
| `0x00` | `STORED` | The object was durably stored. |
| `0x01` | `ALREADY_STORED` | The identical object was already stored. |
| `0x02` | `REJECTED` | The object was valid but refused by policy. |
| `0x03` | `INVALID` | The object content was invalid. |
| `0x04` | `CONFLICT` | The identifier already exists with different immutable content. |

Only `STORED` and `ALREADY_STORED` complete successful submission.

A node must not return `STORED` before durable storage has completed.

---

## 14. ERROR

`ERROR` reports failure of a request that is not represented by an object-processing `ACK`.

Payload:

| Order | Size | Field |
|------:|-----:|-------|
| 1 | 1 | `request_operation` |
| 2 | 1 | `error_code` |
| 3 | 1 | `detail_length` |
| 4 | variable | `detail` |

`detail` is optional human-readable UTF-8 text. Clients must make decisions from `error_code`, not by parsing `detail`.

Error codes:

| Code | Name | Meaning |
|-----:|------|---------|
| `0x01` | `INVALID` | The request frame or parameters are invalid. |
| `0x02` | `UNAUTHORIZED` | The user is not authenticated or not permitted. |
| `0x03` | `NOT_FOUND` | The requested object does not exist or is not visible to the user. |
| `0x04` | `UNSUPPORTED` | The requested operation or feature is unsupported. |
| `0x05` | `BUSY` | The node cannot process the request temporarily. |
| `0x06` | `INTERNAL` | The node failed while processing an otherwise valid request. |

For `GET_BULLETIN`, an unknown bulletin identifier produces `ERROR / NOT_FOUND`.

---

## 15. Reliability and idempotency

- Clients must persist submitted messages before transmission.
- Retries must reuse the original identifier and exact immutable content.
- Nodes must process duplicate submissions idempotently.
- An identifier reused with different content must produce `ACK / CONFLICT`.
- Transport acknowledgements do not replace `ACK / STORED` or `ACK / ALREADY_STORED`.
- A client must not advance an incremental synchronization point until the matching `END` frame has been received and validated.
- Repeating an incremental request with the same `since` value is safe and may return the same objects again.

---

## 16. Deferred protocol details

The following remain outside version 0.1 or require a later extension:

- bulletin publication;
- maximum private-message body policy below the frame limit;
- objects larger than one Core-frame payload;
- attachments and files;
- message deletion or editing;
- read receipts;
- groups and conversations;
- federation and node-to-node synchronization;
- cryptographic signatures and end-to-end encryption.
