# 06 - Object Model

## Objective

This document defines only the domain concepts of OpenQSP: `User`, `Node`, `Message` and `Bulletin`.

---

## 1. Design principles

The first version of OpenQSP prioritizes:

- simplicity;
- persistence;
- efficiency over low-bandwidth links;
- incremental evolution.

Only the minimum functionality required for a modern BBS is included.

---

## 2. User

A `User` is one unique OpenQSP identity identified by an amateur-radio callsign.

There is exactly **one** OpenQSP user for each amateur-radio callsign.

Examples:

- `EA3GNU`
- `EA1ABC`
- `F4XYZ`

SSIDs and portable or mobile suffixes do not create additional OpenQSP users.

The following all represent the same OpenQSP user, `EA3GNU`:

- `EA3GNU`
- `EA3GNU-1`
- `EA3GNU-10`
- `EA3GNU/P`
- `EA3GNU/M`

SSIDs such as `-1` or `-10`, and operating suffixes such as `/P` or `/M`, are transport concepts. They **MUST NOT** be part of the OpenQSP identity, be stored as separate user identities or create separate mailboxes. Identity resolution removes these suffixes and uses the uppercase base callsign.

OpenQSP version 0.1 does not define user-created BBS identities, secondary accounts or device identities.

---

## 3. Object

An object is a persistent unit of application data stored by an OpenQSP node.

Version 0.1 defines two object types:

- `Message`;
- `Bulletin`.

Objects are immutable after creation. Corrections create a new object. Transport retries and
duplicate detection are not part of persistent object identity.

### 3.1 Common properties

Each object has:

- `type`: object type;
- `author`: OpenQSP user who created it;
- `created_at`: UTC creation timestamp;
- type-specific content.

OpenQSP does not require an identifier that is globally unique across objects or object types.

---

## 4. Message

A `Message` is a private object addressed from one OpenQSP user to another.

Fields:

- `sequence`: the server-assigned position in the recipient's mailbox;
- `author`;
- `recipient`;
- `created_at`;
- `body`.

The `recipient` is the OpenQSP user whose mailbox contains the message.

`sequence` is an unsigned 32-bit value scoped to that recipient mailbox. A message is
identified by `(recipient, sequence)`: `(EA3GNU, 17)` and `(EA3ABC, 17)` are different
messages. Each mailbox has its own monotonically increasing sequence space.

A message addressed to `EA3GNU` belongs to the `EA3GNU` mailbox. It is not addressed separately to `EA3GNU-1`, `EA3GNU-10` or any device.

---

## 5. Bulletin

A `Bulletin` is a public news object.

Fields:

- `sequence`: a server-assigned, node-local unsigned 32-bit value;
- `author`;
- `created_at`;
- `title`;
- `body`.

A bulletin has no recipient.
Its sequence is both its synchronization position and its bulletin reference; there is no
separate bulletin identifier.

---

## 6. Node

A `Node` stores `Message` and `Bulletin` objects and makes them available to OpenQSP users.

A node is not a user and does not obtain a user mailbox merely because it has a radio callsign.

---

## 7. No device entity

OpenQSP version 0.1 does not identify or model user devices.

A user may access the same mailbox from multiple clients, but all of them act as the same callsign identity.

Per-device delivery, synchronized read state and interface preferences are outside the scope of version 0.1.

---

## 8. Scope of version 0.1

Supported:

- one unique user identity per callsign;
- private messages;
- public bulletins;
- persistent immutable objects.

Out of scope:

- files;
- chat rooms;
- groups;
- conversations;
- device identities;
- synchronized read state;
- permissions beyond basic authenticated authorship;
- encryption and signatures.
