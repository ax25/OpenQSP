# 06 - Object Model

## Objective

This document defines the conceptual model of OpenQSP.

It intentionally avoids binary encoding, transport details and implementation.

---

# Design Principles

The first version of OpenQSP prioritizes:

- Simplicity
- Persistence
- Transport independence
- Low bandwidth efficiency
- Incremental evolution

Only the minimum functionality required for a modern BBS is included.

---

# User

A user is uniquely identified by a callsign.

Examples:

- EA3GNU
- EA1ABC
- F4XYZ

The following are NOT different users:

- EA3GNU-1
- EA3GNU-10
- EA3GNU/P
- EA3GNU/M

These suffixes belong to transport-specific addressing (for example APRS) and are not part of the OpenQSP identity.

---

# Objects

Everything stored by OpenQSP is an object.

Version 1 defines only:

- Message
- Bulletin

Additional object types can be added in future versions.

## Message

Fields:

- id
- from
- to
- created_at
- body

## Bulletin

Fields:

- id
- from
- created_at
- title
- body

---

# Node

A node stores objects and serves clients.

A node is not a user.

---

# User activity

Nodes maintain a temporary activity state for users.

Activity is local to each node and is not synchronized.

Any valid operation updates the user's last activity.

After a configurable timeout the user becomes inactive.

This mechanism allows transports such as APRS to deliver new information proactively while the user is considered active, without requiring a permanent connection.

---

# Scope of Version 1

Supported:

- Private messages
- Public bulletins
- Internet transport
- APRS transport

Out of scope:

- Files
- Chat
- Groups
- Presence synchronization
- Device synchronization
- Permissions
- Encryption
