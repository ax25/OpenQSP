# AD-01 — Domain Model

**Status:** Draft  
**Version:** 0.1  
**Last Updated:** 2026-08-06

---

# Purpose

This document defines the conceptual domain model of OpenQSP.

Its purpose is to describe the entities that exist within the system, their responsibilities, and the relationships between them.

This document intentionally avoids implementation details such as programming languages, database schemas, APIs, network protocols or user interface design.

The domain model serves as the foundation for every architectural decision within OpenQSP.

---

# Scope

This document defines:

- The conceptual entities of OpenQSP.
- Their responsibilities.
- Their relationships.
- Their lifecycle.
- Their ownership.

This document does not define:

- Database tables.
- REST APIs.
- WebSocket APIs.
- Packet formats.
- APRS transport.
- Internal server implementation.

Those topics are covered by dedicated architecture documents.

---

# Design Principles

The OpenQSP domain model follows a small number of fundamental principles.

## Server Authority

The OpenQSP server is the single source of truth.

Clients cache information but never own it.

---

## Transport Independence

The application model is completely independent from the transport layer.

Messages have exactly the same meaning whether they travel through:

- Internet
- APRS
- AX.25 Packet
- LoRa
- VARA
- Future transports

---

## Persistent by Default

Communication is persistent.

Objects are never considered transient unless explicitly defined otherwise.

---

## Explicit State

Every entity has a well-defined lifecycle.

State transitions are always explicit.

---

## Stable Identity

Every entity owns a stable identifier.

Identifiers never depend on the transport being used.

---

## Extensibility

New transports, services and features should be addable without modifying the conceptual domain model.

Whenever possible, extensions should introduce new entities rather than changing existing ones.
