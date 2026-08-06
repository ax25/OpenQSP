# OpenQSP Protocol

## Purpose

This document defines the first usable version of the OpenQSP application protocol.

OpenQSP is independent from the transport. The Core produces and consumes binary OpenQSP frames. APRS, Packet, LoRa, TCP or any other transport only carries those frames and may add its own framing or text-safe encoding.

This first version is intentionally small. It only defines what is needed to create and acknowledge a private persistent message.

---

## 1. Scope of version 0.1

Version 0.1 supports:

- users identified by amateur-radio callsign;
- private messages from one user to another;
- persistent storage;
- duplicate-safe delivery;
- acknowledgement after storage;
- offline reception and later mailbox access.

Version 0.1 does not yet define:

- bulletins;
- chat rooms;
- attachments;
- message editing or deletion;
- encryption or signatures;
- node discovery;
- synchronization by ranges;
- callsign dictionaries;
- compression;
- transport-specific fragmentation.

---

## 2. Identities and destinations

OpenQSP distinguishes three concepts.

### 2.1 User identity

A user is identified by a normalized amateur-radio callsign.

Example:

```text
EA3GNU
```

The callsign is stored in uppercase ASCII. Version 0.1 permits the characters `A-Z`, `0-9`, `/` and `-`, with a maximum encoded length of 12 bytes.

### 2.2 Message recipient

A private `MESSAGE` object contains a `recipient` field.

This field means:

> the OpenQSP user whose mailbox contains the message.

It is permanent application data. It remains unchanged when the object is copied, stored or forwarded between nodes.

Example:

```text
author    = EA3GNU
recipient = EA1ABC
```

The recipient is not necessarily the station or node currently carrying the frame.

### 2.3 Transport destination

A transport may have its own temporary destination, such as an APRS station, TCP server or LoRa gateway.

That destination is outside the OpenQSP object and is not stored as part of the message.

A frame carrying a message for `EA1ABC` may therefore be sent to an intermediate OpenQSP node such as `EA3NODE-1`.

---

## 3. Binary conventions

Unless explicitly stated otherwise:

- integers are unsigned;
- multi-byte integers use network byte order (big-endian);
- text uses UTF-8;
- callsigns use uppercase ASCII;
- lengths count bytes, not characters;
- no field uses a terminator byte;
- malformed or truncated frames must be rejected.

---

## 4. Common frame header

Every OpenQSP frame starts with the following 4-byte header.

| Offset | Size | Field | Description |
|-------:|-----:|-------|-------------|
| 0 | 1 | `version` | Protocol version. Version 0.1 uses `0x01`. |
| 1 | 1 | `operation` | Operation code. |
| 2 | 1 | `flags` | Operation flags. Version 0.1 requires `0x00`. |
| 3 | 1 | `payload_length` | Number of bytes following the header. |

The maximum payload in a single version 0.1 Core frame is therefore 255 bytes.

This limit does not imply that every transport can carry 255 bytes in one packet. Fragmentation belongs to the transport adapter and will be defined separately.

---

## 5. Operations

Version 0.1 defines two operations.

| Code | Name | Purpose |
|-----:|------|---------|
| `0x01` | `CREATE_MESSAGE` | Create and store one private message. |
| `0x02` | `ACK_OBJECT` | Confirm that an object was processed and stored. |

Unknown operation codes must be rejected in version 0.1.

---

## 6. CREATE_MESSAGE

`CREATE_MESSAGE` creates an immutable private message object.

### 6.1 Payload format

| Order | Size | Field | Description |
|------:|-----:|-------|-------------|
| 1 | 8 | `object_id` | Globally unique random 64-bit identifier. |
| 2 | 4 | `created_at` | Unix timestamp in UTC seconds. |
| 3 | 1 | `author_length` | Length of `author`. |
| 4 | variable | `author` | Sender's normalized callsign. |
| 5 | 1 | `recipient_length` | Length of `recipient`. |
| 6 | variable | `recipient` | Recipient user's normalized callsign. |
| 7 | 1 | `body_length` | Length of `body`. |
| 8 | variable | `body` | UTF-8 message body. |

Version 0.1 has no subject field. A message is only a short body, similar to an instant message or mailbox note. A subject may be added by a later compatible operation or object type if it proves necessary.

### 6.2 Author

The `author` identifies the user who created the message.

Authentication of that identity is outside the binary frame itself. The accepting OpenQSP server must obtain or verify the authenticated user through the active session or transport policy and must reject a frame whose `author` is not permitted for that session.

### 6.3 Recipient

The `recipient` identifies the destination mailbox.

When `EA3GNU` is logged in, the server returns messages whose recipient is `EA3GNU`. Logging in does not add or modify the recipient field.

### 6.4 Object identifier

The sender generates a random 64-bit `object_id` before the first transmission.

Every retry of the same message must reuse the same identifier.

If a node receives a `CREATE_MESSAGE` with an `object_id` it has already stored:

- it must not create a duplicate message;
- it must compare the received immutable content with the stored content;
- if the content matches, it may return the previous successful ACK;
- if the content differs, it must reject the frame as an identifier conflict.

### 6.5 Immutability

A version 0.1 message cannot be modified after creation.

Corrections are sent as a new message with a new `object_id`.

---

## 7. ACK_OBJECT

`ACK_OBJECT` confirms the result of processing one object.

It is an application acknowledgement, not a transport acknowledgement.

A transport may separately confirm that a packet was received. `ACK_OBJECT` means that OpenQSP parsed the operation and reached a durable processing result.

### 7.1 Payload format

| Order | Size | Field | Description |
|------:|-----:|-------|-------------|
| 1 | 8 | `object_id` | Identifier of the acknowledged object. |
| 2 | 1 | `status` | Processing result. |

### 7.2 Status codes

| Code | Name | Meaning |
|-----:|------|---------|
| `0x00` | `STORED` | The object is durably stored. |
| `0x01` | `ALREADY_STORED` | The identical object was already stored. |
| `0x02` | `REJECTED` | The object was validly parsed but refused. |
| `0x03` | `INVALID` | The frame or object was malformed. |
| `0x04` | `CONFLICT` | The object ID exists with different content. |

Only `STORED` and `ALREADY_STORED` complete successful delivery to the receiving OpenQSP node.

They do not necessarily mean that the recipient has read the message.

---

## 8. Sending a private message

Assume user `EA3GNU` is authenticated and writes:

```text
recipient = EA1ABC
body      = Hola, ¿estás conectado?
```

The client performs these steps:

1. Normalize and validate `EA3GNU` and `EA1ABC`.
2. Generate a random 64-bit `object_id`.
3. Record the current UTC Unix timestamp.
4. Build the binary `CREATE_MESSAGE` frame.
5. Store the frame in its local outgoing queue.
6. Give the frame to the selected transport adapter.
7. Retry according to transport policy until a successful `ACK_OBJECT` is received or the message expires.
8. Remove the item from the pending queue only after `STORED` or `ALREADY_STORED`.

The receiving node performs these steps:

1. Reassemble or decode the transport payload if needed.
2. Parse the OpenQSP header and `CREATE_MESSAGE` payload.
3. Validate lengths, callsigns, timestamp policy and authenticated author.
4. Check `object_id` for duplicates or conflicts.
5. Store the message durably in the recipient mailbox.
6. Return `ACK_OBJECT`.

Later, when `EA1ABC` opens a session, the server queries the mailbox using:

```text
recipient = EA1ABC
```

No live end-to-end connection between `EA3GNU` and `EA1ABC` is required.

---

## 9. Binary example

For this example:

```text
object_id = 0x0123456789ABCDEF
created_at = 0x66B36A00
author = EA3GNU
recipient = EA1ABC
body = Hola
```

The `CREATE_MESSAGE` payload occupies 31 bytes:

```text
01 23 45 67 89 AB CD EF   object_id
66 B3 6A 00               created_at
06                        author_length
45 41 33 47 4E 55         "EA3GNU"
06                        recipient_length
45 41 31 41 42 43         "EA1ABC"
04                        body_length
48 6F 6C 61               "Hola"
```

The complete frame occupies 35 bytes:

```text
01 01 00 1F               version, operation, flags, payload_length
01 23 45 67 89 AB CD EF
66 B3 6A 00
06 45 41 33 47 4E 55
06 45 41 31 41 42 43
04 48 6F 6C 61
```

The corresponding successful ACK occupies 13 bytes:

```text
01 02 00 09               version, operation, flags, payload_length
01 23 45 67 89 AB CD EF   object_id
00                        STORED
```

---

## 10. Reliability rules

- The sender must persist pending messages before transmission.
- Retries must reuse the original `object_id` and exact object content.
- Receivers must process duplicate objects idempotently.
- An ACK must only report `STORED` after durable storage.
- Retry timing and maximum lifetime are implementation or transport policy in version 0.1.
- Read receipts are not defined.

---

## 11. Architectural boundary

The OpenQSP Core knows that `CREATE_MESSAGE` contains an author, a recipient and a body because version 0.1 defines this concrete operation.

The transport adapter does not interpret those fields. It only carries the binary frame and deals with transport concerns such as addressing, packet size, fragmentation, retries at link level or text-safe encoding.

This intentionally concrete first version takes priority over introducing a generic object framework too early. Generic operations, extensible field encoding and additional object types can be added after the first end-to-end implementation proves what is actually needed.
