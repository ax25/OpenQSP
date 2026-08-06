# 06 - Object Model

## Objective

This document defines the conceptual model of OpenQSP.

It intentionally excludes binary encoding, transport behavior and implementation details.

---

## 1. Design principles

The first version of OpenQSP prioritizes:

- simplicity;
- persistence;
- transport independence;
- efficiency over low-bandwidth links;
- incremental evolution.

Only the minimum functionality required for a modern BBS is included.

---

## 2. User

A user is one unique OpenQSP identity identified by an amateur-radio callsign.

There is exactly one OpenQSP user for each normalized base callsign.

Examples:

- `EA3GNU`
- `EA1ABC`
- `F4XYZ`

Transport or operating suffixes do not create additional OpenQSP users.

The following all represent the same OpenQSP user, `EA3GNU`:

- `EA3GNU`
- `EA3GNU-1`
- `EA3GNU-10`
- `EA3GNU/P`
- `EA3GNU/M`

APRS SSIDs such as `-1` or `-10`, and operating suffixes such as `/P` or `/M`, are removed when resolving the OpenQSP identity.

They may still be used by a transport for delivery addressing, but they must not be stored as separate user identities or used to create separate mailboxes.

OpenQSP version 0.1 does not define user-created BBS identities, secondary accounts or device identities.

---

## 3. Object

An object is a persistent unit of application data stored by an OpenQSP node.

Version 0.1 defines two object types:

- `Message`;
- `Bulletin`.

Objects are immutable after creation. A retry of the same object reuses the same identifier and content. Corrections create a new object.

### 3.1 Common properties

Each object has:

- `id`: globally unique 64-bit identifier;
- `type`: object type;
- `author`: OpenQSP user who created it;
- `created_at`: UTC creation timestamp;
- type-specific content.

The binary representation is defined in `03-protocol.md`.

---

## 4. Message

A `Message` is a private object addressed from one OpenQSP user to another.

Fields:

- `id`;
- `author`;
- `recipient`;
- `created_at`;
- `body`.

The `recipient` is the OpenQSP user whose mailbox contains the message.

It is application data and remains unchanged regardless of which APRS address, gateway, server or other transport endpoint carries the object.

A message addressed to `EA3GNU` belongs to the `EA3GNU` mailbox. It is not addressed separately to `EA3GNU-1`, `EA3GNU-10` or any device.

---

## 5. Bulletin

A `Bulletin` is a public news object.

Fields:

- `id`;
- `author`;
- `created_at`;
- `title`;
- `body`.

A bulletin has no recipient.

Clients may first request a compact list of bulletin headers and then request the complete content of a selected bulletin.

---

## 6. Node

A node stores objects and serves OpenQSP clients.

A node is not a user and does not obtain a user mailbox merely because it has a radio callsign or APRS address.

Operational information maintained by a node, such as transport addresses, recent activity, retries or delivery queues, is not part of the object model.

---

## 7. No device entity

OpenQSP version 0.1 does not identify or model user devices.

A user may access the same mailbox from multiple clients or transports, but all of them act as the same callsign identity.

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
- global presence;
- permissions beyond basic authenticated authorship;
- encryption and signatures.
