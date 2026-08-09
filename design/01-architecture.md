# OpenQSP Architecture

This document describes the overall architecture of OpenQSP.

It defines the major building blocks, their responsibilities, and the way they interact. It intentionally avoids implementation details such as programming languages, frameworks, database engines, or transport-specific packet formats.

---

## 1. High-Level Architecture

```text
                    +----------------------+
                    |      OpenQSP App     |
                    +----------+-----------+
                               |
                     OpenQSP Application Protocol
                               |
                    +----------+-----------+
                    |   OpenQSP Server     |
                    +----------+-----------+
                               |
                 +-------------+-------------+
                 |                           |
          Persistent Storage         Transport Layer
                                             |
                 +--------------+------------+-------------+
                 |              |                          |
               APRS         Internet                  Future
                                                  Transports
```

OpenQSP uses one application protocol across every supported transport.

Transport implementations carry protocol data but do not redefine its meaning.

---

## 2. Main Building Blocks

### Client

The client is the user-facing application.

Responsibilities:

- Present conversations, messages, bulletins, and delivery state.
- Store local data required for offline operation.
- Create messages and other user-generated data while disconnected.
- Synchronize local state with the server when connectivity becomes available.
- Encode and decode the OpenQSP application protocol.

The client does not select network-wide delivery routes or apply server-side authorization rules.

### OpenQSP Application Protocol

The application protocol defines the shared language used by clients and the server.

Responsibilities:

- Define operations and message semantics.
- Define scoped persistent references and synchronization sequences.
- Define durable results, errors, and synchronization operations.
- Preserve the same meaning across all transports.

The protocol does not define how APRS, Internet, Packet, LoRa, VARA, or any other transport carries its data.

### Server

The server is the authoritative coordinator once data has been accepted and synchronized.

Responsibilities:

- Maintain shared system state.
- Manage identities and permissions.
- Store and retrieve persistent messages and bulletins.
- Coordinate synchronization between clients.
- Track delivery attempts and acknowledgements.
- Select delivery routes according to availability and policy.
- Coordinate transport adapters.

The server does not own client-only presentation state and does not depend on a specific user interface or transport.

### Transport Layer

The transport layer connects OpenQSP to communication media.

Responsibilities:

- Accept outbound protocol units from the server or client.
- Encode them for a specific transport.
- Receive transport data and reconstruct protocol units.
- Report delivery capabilities, failures, and acknowledgements when the transport supports them.

A transport adapter must not change the meaning of an OpenQSP operation or implement domain rules.

### Persistent Storage

Persistent storage retains server-owned state.

Responsibilities:

- Store domain objects and delivery state.
- Support durable queues and synchronization history.
- Preserve accepted data across restarts and temporary failures.

Storage does not decide routing, permissions, or business rules.

---

## 3. Responsibility Matrix

| Building block | Owns or coordinates | Must not own |
|---|---|---|
| Client | User interaction, local state, offline-created data | Network-wide routing policy |
| Application protocol | Shared operation semantics | Transport-specific framing |
| Server | Shared state, authorization, routing, synchronization | User interface state |
| Transport layer | Transport encoding and movement of data | Domain rules |
| Persistent storage | Durable server state | Routing or authorization decisions |

---

## 4. Data Flow

### Internet-connected client

```text
Client
  |
  | OpenQSP protocol over HTTPS or WebSocket
  v
Server
  |
  v
Persistent storage
```

### Radio delivery through a transport adapter

```text
Client or server operation
  |
  v
OpenQSP server
  |
  v
Transport selection
  |
  v
Transport adapter
  |
  v
APRS / Packet / LoRa / VARA / other medium
```

### Offline client

```text
User creates data
  |
  v
Client stores it locally
  |
  | connectivity becomes available
  v
Synchronization with server
  |
  v
Server accepts, persists, and routes it
```

A client may be the only holder of newly created data while offline. After the server accepts that data, the server becomes the authoritative coordinator for shared state and delivery.

---

## 5. Core Design Decisions

- OpenQSP has one application protocol and multiple transports.
- Clients are capable of meaningful offline operation.
- The server coordinates shared state after synchronization.
- Transport adapters are replaceable and isolated from domain rules.
- Persistent queues are part of the architecture, not an optional optimization.
- Delivery state is distinct from message content.
- Components communicate through explicit contracts rather than transport-specific assumptions.

---

## 6. Open Questions

The following architectural topics remain intentionally unresolved:

- Whether multiple OpenQSP servers will federate.
- How transport preference and fallback policies are represented.
- Which conflict-resolution rules are needed during synchronization.
- How message expiration and retention policies are defined.
- Whether attachments belong in the initial protocol or a later extension.

## M6 identity and session boundary

Internet transports authenticate against persistent callsign accounts before creating a runtime session. The boundary is `transport -> account authentication/session -> ServerCore -> stores`: sockets move bytes, sessions carry the verified normalized identity and presence, Core authorizes application operations, and SQLite owns durable state. A session is not an account or socket identity. More than one active session may bind the same account, and each receives eligible push events.
