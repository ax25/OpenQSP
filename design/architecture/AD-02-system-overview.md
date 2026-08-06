# AD-02 — System Overview

**Status:** Draft  
**Version:** 0.1  
**Last Updated:** 2026-08-06

---

# Purpose

This document describes the high-level architectural decomposition of OpenQSP.

It defines the major architectural components of the system, their responsibilities, their interaction boundaries and the allowed dependency directions.

Conceptual definitions are described in AD-01. This document focuses exclusively on system structure.

---

# Architectural Boundaries

The OpenQSP architecture is intentionally divided into independent components.

Each component owns a well-defined responsibility and communicates with other components only through clearly defined interfaces.

Components must never assume knowledge about the internal implementation of another component.

---

# Major Components

The OpenQSP architecture is composed of the following major components:

- Client
- Application Protocol
- Server
- Transport Adapters
- Persistent Storage

Each component may evolve independently provided its public contract remains stable.

---

# Component Responsibilities

| Component | Primary Responsibility | Must Not |
|-----------|------------------------|----------|
| Client | User interaction and local presentation | Implement server-side business rules |
| Application Protocol | Define application semantics | Depend on any transport |
| Server | Execute business logic and coordinate the system | Implement transport-specific logic |
| Transport Adapter | Translate between the application protocol and a transport | Contain business rules |
| Persistent Storage | Persist system state | Execute application logic |

---

# Component Interactions

Components communicate only with adjacent architectural layers.

No component should bypass another component in order to access internal functionality.

This keeps the architecture modular and allows components to be replaced independently.

---

# Dependency Rules

The dependency direction is strictly top-down:

Client → Application Protocol → Server → Transport Adapter / Persistent Storage

Lower layers must never depend on higher layers.

---

# Extension Points

OpenQSP is designed to be extended by introducing new implementations of existing architectural components rather than modifying the architecture itself.

Examples include:

- Additional transport adapters.
- Alternative client implementations.
- Different storage backends.
- Additional server services.

Such extensions should preserve the architectural boundaries defined in this document.
