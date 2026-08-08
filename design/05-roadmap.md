# 05 - Roadmap

## Purpose

This document defines the planned evolution of OpenQSP through small, verifiable milestones.

A milestone is complete only when its stated acceptance criteria are satisfied. Design documents describe the required behaviour; implementation milestones prove that behaviour with working code and automated tests.

Development and laboratory tools evolve alongside the implementation. They are permanent project tools, not disposable test scripts. Their role and progression are described in `../tools/README.md`.

---

## 1. Current project phase

OpenQSP has completed the version 0.1 minimum local node core and its first development Internet transport.

The following design foundations are complete for version 0.1:

- high-level architecture;
- domain boundaries;
- core object model;
- client/node logical protocol;
- binary protocol operations;
- transport responsibilities;
- node storage semantics;
- protocol limits, validation and errors;
- canonical binary examples and test vectors.

Relevant documents:

- `01-architecture.md`;
- `02-domain.md`;
- `03-protocol.md`;
- `04-transports.md`;
- `06-object-model.md`;
- `07-client-node-protocol.md`;
- `08-node-storage.md`;
- `09-protocol-examples.md`.

**Milestone 5 - Internet transport is complete.**

Before implementing the APRS transport, the next server-side work should close the remaining production gaps that affect every transport: authentication, authenticated session lifecycle, server-initiated delivery/presence, and capability discovery. These concerns must remain transport-independent so TCP, APRS and future adapters share the same application behaviour.

---

## 2. Milestone 0 - Design baseline

**Status: complete**

Objective: establish one coherent version 0.1 specification before implementation.

Acceptance criteria:

- one OpenQSP user identity per normalized base callsign;
- version 0.1 objects limited to private messages and public bulletins;
- no device, conversation, read-state or federation model;
- client/node operations defined;
- binary layouts and operation codes defined;
- synchronization uses per-recipient mailbox and node-local bulletin sequences;
- durable storage, transport reliability and cursor rules are separated;
- limits and errors defined;
- reference binary vectors available.

---

## 3. Milestone 1 - Protocol codec

**Status: complete**

Objective: implement a transport-independent encoder and decoder for OpenQSP Core frames.

Scope:

- parse and validate the 4-byte Core header;
- encode and decode every version 0.1 request and response;
- enforce field limits and UTF-8 rules;
- expose typed in-memory request and response objects;
- reject malformed, truncated and oversized frames safely;
- create `tools/frame_tool.py` as the first interactive protocol laboratory tool.

`frame_tool.py` must use the production codec and support at least:

- decoding a hexadecimal Core frame into named fields;
- encoding supported operations from human-readable arguments;
- validating frames and reporting the protocol error category;
- displaying canonical hexadecimal output suitable for comparison with `09-protocol-examples.md`.

Acceptance criteria:

- every valid vector in `09-protocol-examples.md` decodes to the expected fields;
- encoding those fields reproduces the exact canonical bytes;
- every documented invalid vector is rejected with the expected error category;
- unknown versions, operations and flags are handled as specified;
- tests cover all operation types and boundary sizes;
- `frame_tool.py` can inspect and generate the same canonical frames used by the automated tests;
- the codec and frame tool have no dependency on sockets, APRS, WebSocket or database code.

---

## 4. Milestone 2 - Persistent object store

**Status: complete**

Objective: implement the storage contract defined in `08-node-storage.md`.

Initial implementation target:

- SQLite;
- explicit schema migrations;
- transactional writes;
- separate sequence space per recipient mailbox and one node-local bulletin sequence space;
- indexes for mailbox and bulletin retrieval.

Development scenarios should exercise storage behaviour directly, including per-mailbox allocation, cursor progression, concurrency and restart persistence. Duplicate suppression and retry transactions for unreliable links belong to transport-specific scenarios.

Acceptance criteria:

- a new message is stored atomically and receives a stable sequence;
- different mailboxes may contain the same sequence number;
- message insertion and recipient-mailbox sequence allocation are atomic;
- messages can be retrieved by recipient and `since` cursor;
- bulletin headers can be retrieved incrementally;
- complete bulletins can be retrieved by their node-local sequence;
- data and sequence state survive process restart;
- cursor and pagination behaviour matches `03-protocol.md` and `08-node-storage.md`;
- automated tests cover rollback and restart scenarios;
- repeatable storage scenarios exist under `tools/scenarios/` or the equivalent test harness.

---

## 5. Milestone 3 - Minimum server core

**Status: complete**

Objective: connect authenticated request context, protocol codec and persistent storage without implementing a real network transport.

Minimum internal interface:

```text
handle_frame(authenticated_callsign, frame_bytes)
    -> response_frame_bytes[]
```

Supported client operations:

- `SEND_MESSAGE`;
- `GET_NEW_MESSAGES`;
- `GET_NEW_BULLETINS`;
- `GET_BULLETIN`.

This milestone also introduces `tools/client_sim.py`, a development client that emulates one OpenQSP user and calls the server core through the same public development interface used by scenario tests.

The simulator must use the real protocol codec. It must not bypass protocol semantics by directly manipulating database rows or internal server objects.

Acceptance criteria:

- the authenticated callsign is used as message author;
- the client cannot inject a different author;
- every supported request produces the correct `STORED`, object frames, `END` or `ERROR` response;
- one user cannot retrieve another user's private messages;
- partial multi-item responses never advance a client cursor without `END`;
- malformed frames do not crash or corrupt the node;
- responses reproduce the binary protocol exactly;
- `client_sim.py` can send and retrieve data as an explicitly selected test callsign;
- all tests run without a network connection.

Completion of this milestone defines the first functioning OpenQSP node core.

---

## 6. Milestone 4 - Multi-user scenarios and end-to-end test

**Status: complete**

M4.1 provides the first required scenario: two authenticated test users exchange one private message through the production codec, server core, and persistent store, with automated checks for mailbox isolation. M4.2 and M4.3 originally exercised Core-level retry/idempotency and global identifier collision behaviour under the superseded object-identity design. Those semantics no longer belong to Core: unreliable transports own transaction replay and duplicate suppression, while Core assigns recipient-mailbox sequences. M4.4 implements incremental mailbox synchronization with response-derived cursors, mailbox isolation, suppression of previously delivered messages, and a final empty synchronization. M4.5 adds an isolated empty-mailbox synchronization scenario covering both `since=0` and a completed cursor, including cursor stability in the presence of unrelated mailbox activity.
M4.6 adds mailbox pagination with a page size of two, response-derived `END.next_since` cursors and explicit `has_more` transitions. Activity is interleaved across independent recipient mailboxes while checks preserve mailbox isolation, per-mailbox monotonic ordering, correct cursor progression, pagination, and no loss.
M4.7 implements node-restart recovery by reconstructing the complete local node over the same SQLite file. It verifies durable private messages and sequence allocation, continued use of a pre-restart `END.next_since` cursor, duplicate-free incremental synchronization, and unchanged mailbox isolation through the production client, codec, and server stack. M4.8 adds development-seeded public bulletin header synchronization, response-derived cursors, complete bulletin retrieval by synchronized sequence, incremental and empty follow-ups, and missing-bulletin handling. M4.9 closes the milestone with one integrated conformance workflow across authenticated messaging, isolation, restart persistence, cursor resumption, sequence continuity, bulletin synchronization and full retrieval through the production codec, `ServerCore`, and persistent stores. Detailed behaviour remains covered by the maintained scenarios that still match the current architecture.

Objective: prove the complete version 0.1 workflow with repeatable local scenarios using the reference simulator.

Required scenarios include at least:

- two users exchanging a private message;
- incremental mailbox synchronization;
- empty mailbox synchronization;
- pagination and `has_more`;
- node restart with persistent state;
- bulletin header synchronization and complete bulletin retrieval;
- transport-specific retry and duplicate-suppression scenarios once an unreliable transport is implemented.

Acceptance criteria:

- two test users can exchange private messages through one node;
- the recipient can synchronize messages incrementally;
- bulletin headers and complete bulletins can be retrieved;
- synchronization resumes correctly after client and node restarts;
- scenarios are repeatable and do not depend on manual database editing;
- the complete workflow is exercised by automated end-to-end tests;
- unreliable transports can add retry and duplicate suppression without changing Core object identity or storage semantics.

The reference client and scenarios are development tools, not the final user application.

---

## 7. Milestone 5 - Internet transport

**Status: complete**

The milestone was delivered as:

- **M5.1 - Minimal Internet TCP Transport**;
- **M5.2 - Client Transport Abstraction**;
- **M5.3 - Transport-Neutral Scenario Harness**;
- **M5.4 - TCP Client and Remote Scenario Integration**;
- **M5.5 - Internet Transport Conformance and Closure**.

Objective: expose the minimum node through one simple Internet transport.

TCP is the first development Internet transport. Each connection begins with a bounded `CALLSIGN <normalized-callsign>\n` handshake. This identification is **development-only and is not production authentication**. After the handshake, the TCP adapter uses the existing Core header payload-length byte to recover complete frames; the OpenQSP Core frames themselves are unchanged. It forwards each complete request and the connection callsign directly to `ServerCore` and writes the returned frames in order, without inspecting operations or owning protocol or storage logic.

The transport provides the core with:

- one complete OpenQSP frame;
- one authenticated or development-authenticated callsign;
- a way to return one or more response frames.

The TCP server transport is complemented by `TcpTransport` in `client_sim.py`. The simulator has explicit local SQLite and remote TCP modes, and the same transport-neutral scenarios execute either directly against Core or over loopback TCP. The client uses one connection per exchange and the development callsign handshake remains identification only, **not production authentication**.

Remote integration environments own the real TCP listener and test database. Their controlled store access supports development-only bulletin seeding, and their restart operation stops and reconstructs the complete TCP-visible node against the same SQLite file. Reconnection therefore preserves durable messages, sequence continuity, and synchronization cursors without treating a socket as OpenQSP identity.

Acceptance criteria:

- remote clients can perform every version 0.1 operation;
- reconnecting does not lose stored state or change synchronization semantics;
- connection state is not treated as OpenQSP identity;
- transport code does not duplicate protocol or domain rules;
- the same core scenarios can be executed through the Internet transport.

Production-grade authentication remains a later milestone, and development authentication must remain visibly marked as non-production.

---

## 8. Milestone 6 - Production identity, sessions and node capabilities

**Status: next**

Objective: replace development-only callsign identification with a production-capable identity/session boundary and define how a client discovers what a node can do before APRS transport work begins.

Required design and implementation work:

- callsign + password account authentication for normal Internet access;
- a documented offline-client policy so the user application can still open and operate with locally cached state when Internet authentication is unavailable;
- authenticated session lifecycle independent from any particular transport;
- explicit separation between OpenQSP user identity and TCP/APRS connection state;
- server-initiated delivery for connected/active clients without allowing unsolicited frames to satisfy normal request/response exchanges;
- ACTIVE/INACTIVE or equivalent presence semantics needed by proactive delivery;
- capability/service discovery so clients can query which node features or commands are currently available;
- deterministic authorization and error handling for unsupported or unauthorized operations.

Acceptance criteria:

- production TCP access no longer relies on the development-only `CALLSIGN` handshake as authentication;
- authenticated callsign identity is supplied to Core through a transport-independent session boundary;
- reconnecting or changing transport does not create a new OpenQSP identity;
- an active client can receive server-initiated events without corrupting normal request correlation;
- clients can query node capabilities and adapt their UI/available actions accordingly;
- authentication/session/capability tests are repeatable locally and over the development TCP transport;
- no APRS-specific retry, fragmentation or acknowledgement semantics leak into the application/session layer.

---

## 9. Milestone 7 - APRS transport profile and simulator

**Status: planned**

Objective: define, simulate and implement OpenQSP carriage over APRS after the node core and shared session semantics are stable.

Required design work before implementation:

- text-safe encoding;
- fragmentation and reassembly;
- message correlation;
- APRS acknowledgement interaction;
- retry timing and limits;
- peer-scoped duplicate suppression and replay of prior Core results where required;
- channel rate control;
- proactive delivery while the user is locally active.

Before APRS-IS or RF testing, implement `tools/aprs_sim.py` or equivalent to transform between complete OpenQSP Core frames and the defined APRS carriage representation.

The simulator should support controlled fault injection for at least:

- fragment loss;
- duplicate fragments;
- fragment reordering;
- delayed fragments;
- lost acknowledgements.

Acceptance criteria include:

- canonical OpenQSP frames survive APRS encode, fragmentation, reassembly and decode unchanged;
- documented fault scenarios behave predictably;
- retries and duplicate suppression are scoped to the APRS transport and do not create Core object IDs;
- successful exchange is demonstrated locally through the simulator;
- successful exchange is then demonstrated over APRS-IS before testing over RF.

APRS must remain a transport adapter and must not redefine OpenQSP object or protocol semantics.

---

## 10. Milestone 8 - User application

**Status: planned**

Objective: implement the first user-facing client after the server and at least one production-capable identity/session path are usable.

Expected minimum features:

- callsign identity configuration and account sign-in;
- local/offline startup using cached local state when the network is unavailable;
- private-message inbox and sending;
- bulletin-header list;
- bulletin download;
- node capability discovery and UI adaptation;
- local persistence;
- independent message and bulletin synchronization cursors;
- clear delivery and error states.

The application platform and framework do not affect the Core protocol.

---

## 11. Test and laboratory layers

OpenQSP development uses four complementary levels:

1. **Unit tests** - verify codec, storage and server functions in isolation.
2. **Protocol vectors** - verify exact binary compatibility with `09-protocol-examples.md`.
3. **Laboratory and scenario tools** - emulate users, workflows and unreliable transports.
4. **Real transports** - verify the same behaviour over Internet, APRS-IS and eventually RF.

Laboratory tools must reuse production protocol code wherever possible. They must not become an alternative implementation of OpenQSP semantics.

---

## 12. Later extensions

The following are intentionally outside the minimum version and require separate design decisions:

- bulletin publication by ordinary clients;
- message deletion or expiration;
- attachments and files;
- groups, channels and conversations;
- read receipts and synchronized read state;
- multiple recipients;
- cryptographic identity, signatures and end-to-end encryption;
- node federation and node-to-node synchronization;
- Packet, LoRa, VARA and additional transports;
- administration and moderation interfaces.

These features must not be added to the version 0.1 core merely because the data model could accommodate them.

---

## 13. Current implementation order

Milestones 0 through 5 are complete. The next work should proceed in this order:

1. define and implement production identity/authentication semantics;
2. introduce the transport-independent authenticated session lifecycle;
3. implement server-initiated delivery and ACTIVE/INACTIVE behaviour;
4. define and implement node capability/service discovery;
5. close Milestone 6 with integrated TCP/session/capability conformance tests;
6. define the APRS transport profile and implement `aprs_sim.py`;
7. validate APRS locally with loss/duplicate/reordering fault injection;
8. validate over APRS-IS and finally RF;
9. begin the first user-facing application on top of the stable identity, capability and synchronization model.

Work may overlap where dependencies permit, but a milestone must satisfy its acceptance criteria before it is considered complete.

---

## 14. Minimum server release definition

The first minimum server release is complete when Milestones 1 through 4 are complete. **That condition is now satisfied:** Milestones 1 through 4 are complete, delivering the minimum local server/core release.

It must demonstrate that:

- a node can start with an empty persistent database;
- one authenticated user can submit a private message;
- the node stores it durably and assigns it a recipient-mailbox sequence;
- the intended recipient can retrieve it incrementally;
- other users cannot retrieve it;
- bulletin headers and bodies can be retrieved;
- protocol errors are deterministic;
- state survives restart;
- the same behaviour can be reproduced through maintained development tools and automated scenarios;
- all required behaviour is covered by automated tests.

Transport-specific retry and duplicate suppression are deliberately outside this Core release definition and must be implemented by transports that require them.

A real APRS adapter, graphical application and production authentication are not required for this first release.

The completed release includes the protocol codec, persistent store, minimum server core, multi-user end-to-end workflows, synchronization, restart persistence, bulletin retrieval, and the development TCP Internet transport. It intentionally has no APRS transport, production-grade authentication, or final user application; those belong to later milestones.
