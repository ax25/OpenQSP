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
- are identified and synchronized by `(recipient, mailbox-local sequence)`.

Each recipient has an independent sequence space for their mailbox. Reliability mechanisms required by an unreliable transport, including retries and deduplication for APRS, belong to that transport adapter rather than the Core application model.

## Public Bulletins

Public bulletin objects intended for information that should be discoverable and retrieved on demand.

Bulletins include:

- author callsign;
- title;
- body;
- one node-local `u32` sequence used as both the synchronization position and the bulletin reference.

Clients can retrieve bulletin headers incrementally and download complete bulletins by sequence. There is no separate bulletin identifier.

## Synchronization

Clients synchronize through node-local monotonic cursors rather than depending on continuous connectivity.

The initial protocol supports:

- `SEND_MESSAGE`;
- `GET_NEW_MESSAGES`;
- `GET_NEW_BULLETINS`;
- `GET_BULLETIN`;
- typed `MESSAGE` and bulletin responses, `STORED` for durable successful storage, `END` for completed retrievals, and `ERROR` for failures.

The Internet API also exposes conversation-oriented state used by the current application, including unread counts, delivery state and explicit read state.

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

The protocol codec is intentionally independent from HTTP, WebSocket, APRS, database and application code so that the same Core semantics can be reused across different transports.

---

# Repositories

OpenQSP is currently split into two repositories:

- **`OpenQSP`** — server, Core protocol implementation, storage, Internet API, APRS transport and development tools.
- **`OpenQSP-App`** — the user-facing Flutter application.

This repository contains the server side:

```text
OpenQSP/
│
├── server/       Server and OpenQSP Core implementation
├── protocol/     Protocol-related documentation
├── design/       Architecture, protocol, storage and roadmap specifications
├── docs/         Internet API and implementation documentation
├── examples/     Example implementations and fixtures
└── tools/        Development and protocol laboratory tools
```

The detailed implementation roadmap is maintained in [`design/05-roadmap.md`](design/05-roadmap.md).

---

# Current Status

OpenQSP is now beyond the original server-only prototype stage. The Core server, Internet messaging path, APRS path and the first real user application are all under active development and have been exercised together.

## Server

Currently implemented in this repository:

- transport-independent OpenQSP Core protocol models and codecs;
- persistent SQLite storage for private messages and bulletins;
- normalized callsign accounts and password-authenticated Internet sessions;
- HTTPS REST API for authentication, server status, message send/sync and conversation state;
- WebSocket realtime events for new messages, delivery updates and read updates;
- per-conversation unread state and explicit read cursors;
- persisted message delivery state (`stored`, `delivered`, `read`);
- authoritative per-user active transport selection between Internet/WebSocket and APRS;
- proactive delivery over the currently active transport, without automatic fallback to a stale transport;
- APRS Base64url carriage, fragmentation/reassembly, APRS ACK/retry, replay protection and deduplication;
- APRS incremental mailbox synchronization and proactive message delivery;
- APRS-IS production connection, verified login, reconnect/backoff, stale-link detection and diagnostic decoded logging;
- deterministic APRS simulation and extensive automated test coverage.

The production deployment is intended to expose the server through **HTTPS/WSS**, with APRS-IS as an outbound server connection. The old native TCP development transport is no longer the intended application transport and is not part of the current client architecture.

## User application

The user application is no longer a future milestone. A separate Flutter client exists in [`OpenQSP-App`](https://github.com/ax25/OpenQSP-App) and already implements the main private-messaging experience.

Current application capabilities include:

- Flutter multiplatform application architecture;
- callsign/password authentication against the Internet API;
- conversation list and private-message UI;
- realtime Internet messaging over WebSocket;
- unread conversation indicators;
- stored / delivered / read message status in the UI;
- persistent local message history independent of the active transport;
- incremental synchronization when reconnecting;
- Android Bluetooth Classic/SPP TNC configuration;
- KISS/APRS client transport work, including real APRS message synchronization and sends;
- APRS server reachability checks, retry/late-response handling and connection diagnostics.

The application currently focuses on **private messages**. Bulletin UI and additional transports remain future work.

## APRS field status

The APRS transport has been tested through APRS-IS and with real RF/IGate paths during client/server development. The current work is focused on robustness on slow and lossy links, minimizing unnecessary RF traffic and ensuring interrupted synchronizations resume safely.

Recent server-side APRS improvements include fail-fast response batches after fragment loss, stale-response supersession, hardened APRS-IS reconnect behavior and human-readable decoded protocol logging.

---

# Roadmap

The original milestone sequence remains useful as historical design context, but the project has already progressed beyond the old M8 placeholder.

- [x] **Milestone 0 — Design baseline**
- [x] **Milestone 1 — Protocol codec**
- [x] **Milestone 2 — Persistent object store**
- [x] **Milestone 3 — Minimum server core**
- [x] **Milestone 4 — Multi-user scenarios and end-to-end tests**
- [x] **Milestone 5 — Internet transport foundation**
- [x] **Milestone 6 — Production identity, sessions and node capabilities**
- [x] **Milestone 7 — APRS transport profile and simulator**
- [x] **Milestone 8 — First user application** — implemented as a separate Flutter repository

Current development is centered on turning those foundations into a usable end-to-end system:

- hardening Internet and APRS transport switching;
- improving APRS behavior over real lossy RF paths;
- completing Android TNC/KISS/APRS integration;
- maintaining durable local/client synchronization semantics;
- extending the application beyond private messages;
- evaluating additional low-bandwidth transports such as Packet, LoRa and VARA.

---

# Development Tools

OpenQSP includes maintained development and laboratory tools that reuse production protocol code.

Available tools include:

```text
tools/frame_tool.py
tools/client_sim.py
tools/aprs_sim.py
```

`frame_tool.py` can:

- decode a hexadecimal OpenQSP Core frame into named fields;
- validate frames and report protocol errors;
- encode supported v0.1 operations from human-readable arguments;
- produce canonical hexadecimal output suitable for comparison with the protocol specification and automated tests.

`client_sim.py` and the remaining development transport tooling are useful for protocol and Core testing, but the current user-facing Internet application uses the HTTPS REST API and WebSocket interface rather than the original native TCP client path.

## Running the server for development

Install the server package in editable mode and start a node:

```console
$ python -m pip install -e server
$ openqsp-server --database /tmp/openqsp.db
```

Provision an account with:

```console
$ openqsp-server --database /tmp/openqsp.db --create-account EA3AAA 'password'
```

The Flutter application can then be configured to use the server's Internet API. In production, HTTPS/WSS should normally be terminated by a reverse proxy in front of the OpenQSP server.

---

# Identity and transport policy

The node uses persistent normalized base-callsign identities. Password authentication applies to Internet sessions; APRS source identity is transport-asserted and account passwords are never transmitted over APRS.

For the current MVP, the server maintains one authoritative active transport per user:

- valid OpenQSP traffic received through APRS can establish APRS as the active path;
- an active authenticated WebSocket session establishes Internet as the active path;
- proactive messages are sent through the currently active path;
- the server does not automatically duplicate or fall back to another stale transport.

This keeps transport selection implicit in real client activity while preserving one logical mailbox identity across Internet and radio links.
