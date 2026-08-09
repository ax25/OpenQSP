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

✅ **Milestone 7 complete — OpenQSP Core v0.1 with TCP and APRS-IS transport paths**

The design baseline and Milestones 1 through 7 are complete. The version 0.1 node supports local Core execution, authenticated TCP Internet access, and the APRS transport profile over APRS-IS.

Currently implemented:

- transport-independent protocol package and typed models;
- OpenQSP Core frame encoder and decoder;
- version 0.1 request and response payload codecs;
- protocol validation and deterministic error handling;
- automated protocol conformance tests against canonical binary examples;
- `tools/frame_tool.py` for inspecting, validating and generating Core frames using the production codec;
- persistent SQLite storage and the minimum `ServerCore`;
- maintained multi-user, synchronization, restart and bulletin scenarios;
- a TCP server and remote client transport supporting all four v0.1 client operations through production codec, Core, and storage paths;
- persistent mailbox and bulletin state, cursors, and sequence allocation across TCP reconnects and full node restarts;
- APRS Base64url carriage, bounded fragmentation/reassembly, native ACK/retry, replay/deduplication, rate/activity state and proactive private-message delivery;
- deterministic APRS simulation with fault injection;
- production APRS-IS connection/reconnection path with verified login and cross-server validation.

Normal TCP access uses persistent callsign accounts and password authentication. APRS identity is transport-asserted, not cryptographically authenticated, and account passwords are never sent over APRS.

M7 live acceptance was completed on 2026-08-09. Real APRS-IS tests covered verified node login, capability discovery, seven-fragment message storage, durable retrieval after node restart, unsolicited proactive delivery, forced TCP disconnect with automatic APRS-IS reconnection, and deliberate cross-server exchanges between distinct Tier-2 servers. See [`design/M7-live-aprsis-acceptance.md`](design/M7-live-aprsis-acceptance.md). RF/IGate field validation remains a later field activity and does not block M7 completion.

The next active milestone is M8, the first user-facing application.

---

# Roadmap

- [x] **Milestone 0 — Design baseline**
- [x] **Milestone 1 — Protocol codec**
- [x] **Milestone 2 — Persistent object store**
- [x] **Milestone 3 — Minimum server core**
- [x] **Milestone 4 — Multi-user scenarios and end-to-end tests**
- [x] **Milestone 5 — Internet transport**
- [x] **Milestone 6 — Production identity, sessions and node capabilities**
- [x] **Milestone 7 — APRS transport profile and simulator**
- [ ] **Milestone 8 — User application** *(next)*

The first minimum server release is defined by completion of Milestones 1 through 4.

Later extensions may include additional transports, richer user interaction models, attachments, cryptographic identity and node federation, but these are not part of the minimum v0.1 implementation.

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

`client_sim.py` runs the same production-encoded v0.1 operations against either a local Core or the development TCP server. Maintained scenarios under `tools/scenarios/` exercise multi-user, synchronization, persistence, and restart workflows through either environment.

## Reference TCP client

Install the server package in editable mode, then run a node and two interactive clients in separate terminals:

```console
$ python -m pip install -e server
$ openqsp-server --database /tmp/openqsp.db
```

In another terminal:

```console
$ openqsp-client --host 127.0.0.1 --port 8000 --callsign EA3AAA
```

And another:

```console
$ openqsp-client --host 127.0.0.1 --port 8000 --callsign EA3BBB
```

The reference client uses production callsign-and-password authentication and exposes capability discovery and unsolicited events.

## Production identity and offline policy (M6)

The node now uses persistent normalized callsign accounts and password authentication, transport-independent active sessions, best-effort unsolicited private-message delivery, and capability discovery. Provision an account with `openqsp-server --database openqsp.db --create-account EA3AAA 'password'`; connect with `openqsp-client --callsign EA3AAA` and enter the password securely.

A previously configured future client must be able to open without Internet and inspect locally cached state. Node operations remain pending or unavailable until connectivity and server authentication return. Local application access is not server authentication. No credential/token cache semantics are implied; any future cache requires an explicit security design. APRS source identity is transport-asserted and intentionally separate from password-authenticated Internet sessions. Reconnection and transport changes resolve to the same persistent base-callsign mailbox identity.
