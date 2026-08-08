# OpenQSP

> A modern, transport-independent messaging platform for amateur radio.

OpenQSP is an open-source communication platform designed for amateur radio operators. It provides persistent messaging over multiple transports while exposing a single application protocol and a shared mailbox identity based on the user's callsign.

OpenQSP is **not tied to any specific transport**. APRS is one transport adapter among several possible communication media.

The same architecture is intended to operate over:

- Internet
- APRS
- AX.25 Packet
- LoRa
- VARA FM
- VARA HF
- Future transports

The objective is to provide reliable, store-and-forward communications over slow, intermittent and heterogeneous links without changing the application semantics.

---

# Vision

Modern messaging applications assume permanent Internet connectivity.

OpenQSP starts from the opposite assumption:

> Internet may not exist, but radio still does.

The project aims to offer one consistent messaging model regardless of the transport being used.

Whether a user connects through APRS, Packet, LoRa or the Internet, they interact with the same logical node state, the same callsign identity and the same stored objects.

---

# Core Principles

- Transport-independent application protocol.
- Persistent store-and-forward messaging.
- Optimized for extremely low-bandwidth links.
- Designed for intermittent connectivity.
- One identity per normalized amateur-radio callsign.
- Deterministic synchronization using explicit cursors.
- Clear separation between application protocol and transport adapters.
- Open protocol.
- Extensible architecture.
- Open-source community project.

---

# OpenQSP Core v0.1

Version 0.1 deliberately keeps the application model small.

## Private Messages

Persistent point-to-point messages between amateur-radio callsigns.

Private messages:

- have no subject/title;
- are stored durably by the node;
- can be retrieved incrementally;
- are safe to retry without creating duplicates when the same object identifier is reused with identical content.

## Public Bulletins

Public bulletin objects intended for information that should be discoverable and retrieved on demand.

Bulletins include:

- an identifier;
- author callsign;
- title;
- body;
- node-local synchronization sequence.

Clients can retrieve bulletin headers incrementally and download complete bulletins by identifier.

## Synchronization

Clients synchronize through node-local monotonic cursors rather than depending on continuous connectivity.

The initial protocol supports:

- `SEND_MESSAGE`;
- `GET_NEW_MESSAGES`;
- `GET_NEW_BULLETINS`;
- `GET_BULLETIN`;
- typed message, bulletin, acknowledgement, completion and error responses.

Features such as conversations, groups, attachments, read receipts, synchronized read state and federation are intentionally outside the v0.1 core.

---

# Architecture

```text
                     +----------------------+
                     |      OpenQSP         |
                     |    Application Core  |
                     +----------+-----------+
                                |
                Transport-independent protocol
                                |
          +---------+-----------+-----------+----------+
          |         |           |           |          |
      Internet     APRS      AX.25      LoRa      VARA
```

Transport adapters carry complete OpenQSP Core operations without redefining object semantics, persistence rules or synchronization behaviour.

The protocol codec is intentionally independent from sockets, APRS, WebSocket and database code so that the same Core frames can be reused across different transports.

---

# Repository Structure

```text
OpenQSP/
│
├── app/          Future user-facing client
├── server/       Server and OpenQSP Core implementation
├── protocol/     Protocol-related documentation
├── design/       Architecture, protocol, storage and roadmap specifications
├── examples/     Example implementations and fixtures
└── tools/        Development and protocol laboratory tools
```

The detailed implementation roadmap is maintained in [`design/05-roadmap.md`](design/05-roadmap.md).

---

# Current Status

✅ **Minimum Node Core and Development TCP Transport Implemented — OpenQSP Core v0.1**

The design baseline and Milestones 1 through 5 are complete. The version 0.1
minimum node supports both local Core execution and development TCP Internet
transport.

Currently implemented:

- transport-independent protocol package and typed models;
- OpenQSP Core frame encoder and decoder;
- version 0.1 request and response payload codecs;
- protocol validation and deterministic error handling;
- automated protocol conformance tests against canonical binary examples;
- `tools/frame_tool.py` for inspecting, validating and generating Core frames using the production codec;
- persistent SQLite storage and the minimum `ServerCore`;
- maintained multi-user, retry, synchronization, restart and bulletin scenarios;
- a TCP server and remote client transport supporting all four v0.1 client
  operations through production codec, Core, and storage paths;
- persistent mailbox and bulletin state, cursors, and sequence allocation across
  TCP reconnects and full node restarts.

The TCP connection's `CALLSIGN` handshake is **development-only identification,
not production authentication**. This implementation is not a production-secure
deployment: production authentication, TLS, authorization policy, APRS, server
push, ACTIVE/INACTIVE presence, capability discovery, and an end-user
application remain future work.

---

# Roadmap

- [x] **Milestone 0 — Design baseline**
- [x] **Milestone 1 — Protocol codec**
- [x] **Milestone 2 — Persistent object store**
- [x] **Milestone 3 — Minimum server core**
- [x] **Milestone 4 — Multi-user scenarios and end-to-end tests**
- [x] **Milestone 5 — Internet transport**
- [ ] **Milestone 6 — APRS transport profile and simulator**
- [ ] **Milestone 7 — User application**

The first minimum server release is defined by completion of Milestones 1 through 4.

Later extensions may include additional transports, richer user interaction models, attachments, cryptographic identity and node federation, but these are not part of the minimum v0.1 implementation.

---

# Development Tools

OpenQSP includes maintained development and laboratory tools that reuse production protocol code.

Available tools include:

```text
tools/frame_tool.py
tools/client_sim.py
```

`frame_tool.py` can:

- decode a hexadecimal OpenQSP Core frame into named fields;
- validate frames and report protocol errors;
- encode supported v0.1 operations from human-readable arguments;
- produce canonical hexadecimal output suitable for comparison with the protocol specification and automated tests.

`client_sim.py` runs the same production-encoded v0.1 operations against either
a local Core or the development TCP server. Maintained scenarios under
`tools/scenarios/` exercise multi-user, synchronization, persistence, and
restart workflows through either environment.

## Reference TCP client

Install the server package in editable mode, then run a node and two interactive
clients in separate terminals:

```console
$ python -m pip install -e server
$ openqsp-server --database /tmp/openqsp.db
$ openqsp-client --host 127.0.0.1 --port 8023   # terminal 2: EA3AAA
$ openqsp-client --host 127.0.0.1 --port 8023   # terminal 3: EA3BBB
```

At the first prompt, `send EA3BBB Hello from EA3AAA` stores a private message.
At the second, `new` retrieves it using the mailbox cursor. Use `help` for the
complete command list.

The present TCP handshake is callsign identification only, so the client does
not ask for or transmit a password. Core v0.1 also has no capability-discovery
operation, and the current server does not proactively push messages; the
client's background reader is nevertheless able to receive unsolicited Core
frames when a transport sends them. These are protocol/server limitations, not
alternate client-side wire formats.

---

# Design Philosophy

OpenQSP is **not an APRS application**.

It is a transport-independent communication platform where APRS is one possible transport adapter.

Every design decision prioritizes:

- simplicity;
- deterministic behaviour;
- reliability;
- low bandwidth usage;
- tolerance of intermittent links;
- separation of protocol and transport concerns;
- long-term maintainability.

The minimum version is intentionally small. New concepts are added only when they are required by real use cases and can be specified without weakening the Core model.

---

# Contributing

OpenQSP is in active early implementation.

Protocol behaviour and scope should follow the documents under `design/`, with [`design/05-roadmap.md`](design/05-roadmap.md) defining the current implementation sequence.

Ideas, testing and contributions are welcome as the project evolves.

---

# License

This project is licensed under the GNU General Public License v3.0 (GPL-3.0).
