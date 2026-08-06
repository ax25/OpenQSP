# OpenQSP Protocol

## Purpose

This document defines the OpenQSP application protocol.

The protocol is independent from any transport.

Transport-specific details (APRS, Internet, Packet, LoRa, etc.) are described in `04-transports.md`.

---

## Goals

The protocol is designed to be:

- Transport independent
- Reliable
- Persistent
- Efficient over very low bandwidth links
- Easy to extend

---

## Protocol Rules

The following rules always apply.

- Every operation has a globally unique identifier.
- Operations are idempotent whenever possible.
- Messages remain queued until delivered or expired.
- Synchronization is incremental.
- Transport never changes the meaning of an operation.
- Clients must be able to operate offline.

---

## Operations

| Operation | Purpose |
|-----------|---------|
| Message | Send a user message |
| Ack | Confirm reception |
| Sync | Synchronize pending data |
| Bulletin | Publish or retrieve bulletins |
| Status | Report delivery or protocol status |
| Error | Report protocol errors |

Each operation will be specified in detail as the protocol evolves.

---

## Reliability

Reliable communication is achieved through:

- acknowledgements
- retransmissions
- persistent queues
- synchronization

The retry strategy is implementation-dependent.

---

## Versioning

Every operation belongs to a protocol version.

Future versions should remain backward compatible whenever practical.

---

## Out of Scope

This document does not define:

- APRS transport
- Internet transport
- Binary encoding
- JSON encoding
- Database storage
- Server implementation
- Client implementation

Those topics are covered by other design documents.
