# 05 - Roadmap

## Purpose

This document defines the planned evolution of OpenQSP through small, verifiable milestones.

A milestone is complete only when its stated acceptance criteria are satisfied. Design documents describe the required behaviour; implementation milestones prove that behaviour with working code and automated tests.

Development and laboratory tools evolve alongside the implementation. They are permanent project tools, not disposable test scripts. Their role and progression are described in `../tools/README.md`.

---

## 1. Current project phase

OpenQSP has completed the version 0.1 minimum local node core and its first
development Internet transport.

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

Development scenarios should exercise storage behaviour directly, including per-mailbox
allocation, cursor progression, concurrency and restart persistence. Duplicate suppression and
retry transactions for unreliable links belong to transport-specific scenarios.

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

M4.1 provides the first required scenario: two authenticated test users
exchange one private message through the production codec, server core, and
persistent store, with automated checks for mailbox isolation. M4.2 adds the
identical-message retry after a lost application acknowledgement under the
then-current design. That Core-level retry behaviour and M4.3's old identifier-collision scenario
are superseded by the target architecture: unreliable transports own transaction replay and
duplicate suppression, while Core assigns mailbox sequences. M4.4 implements
incremental mailbox synchronization with response-derived cursors, mailbox
isolation, suppression of previously delivered messages, and a final empty
synchronization. M4.5 adds an isolated empty-mailbox synchronization scenario
covering both `since=0` and a completed cursor, including cursor stability in
the presence of unrelated mailbox activity.
M4.6 adds mailbox pagination with a page size of two, response-derived
`END.next_since` cursors and explicit `has_more` transitions. Activity is interleaved across
independent recipient mailboxes while checks preserve mailbox isolation, per-mailbox monotonic
ordering, correct cursor progression, pagination, and no loss.
M4.7 implements node-restart recovery by reconstructing the complete local
node over the same SQLite file. It verifies durable private messages and
sequence allocation, continued use of a pre-restart `END.next_since` cursor,
duplicate-free incremental synchronization, and unchanged mailbox isolation
through the production client, codec, and server stack. M4.8 adds
development-seeded public bulletin header synchronization, response-derived
cursors, complete bulletin retrieval by synchronized sequence, incremental
and empty follow-ups, and missing-bulletin handling. M4.9 closes the milestone
with one integrated conformance workflow across authenticated messaging,
isolation, restart persistence, cursor resumption, sequence
continuity, bulletin synchronization and full retrieval through the production
codec, `ServerCore`, and persistent stores. Detailed behaviour remains covered
by the individual M4.1-M4.8 scenarios.

Objective: prove the complete version 0.1 workflow with repeatable local scenarios using the reference simulator.

Required scenarios include at least:

- two users exchanging a private message;
- unreliable-transport retry after a lost transport acknowledgement;
- peer-scoped duplicate suppression and replay of a prior Core result;
- incremental mailbox synchronization;
- empty mailbox synchronization;
- pagination and `has_more`;
- node restart with persistent state;
- bulletin header synchronization and complete bulletin retrieval.

Acceptance criteria:

- two test users can exchange private messages through one node;
- an unreliable transport can safely retry after losing its transport acknowledgement;
- the recipient can synchronize messages incrementally;
- bulletin headers and complete bulletins can be retrieved;
- synchronization resumes correctly after client and node restarts;
- scenarios are repeatable and do not depend on manual database editing;
- the complete workflow is exercised by automated end-to-end tests.

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

TCP is the first development Internet transport. Each connection begins with a
bounded `CALLSIGN <normalized-callsign>\n` handshake. This identification is
**development-only and is not production authentication**. After the handshake,
the TCP adapter uses the existing Core header payload-length byte to recover
complete frames; the OpenQSP Core frames themselves are unchanged. It forwards
each complete request and the connection callsign directly to `ServerCore` and
writes the returned frames in order, without inspecting operations or owning
protocol or storage logic.

The transport provides the core with:

- one complete OpenQSP frame;
- one authenticated or development-authenticated callsign;
- a way to return one or more response frames.

The TCP server transport is complemented by `TcpTransport` in
`client_sim.py`. The simulator has explicit local SQLite and remote TCP modes,
and the same transport-neutral scenarios execute either directly against Core
or over loopback TCP. The client uses one connection per exchange and the
development callsign handshake remains identification only, **not production
authentication**.

Remote integration environments own the real TCP listener and test database.
Their controlled store access supports development-only bulletin seeding, and
their restart operation stops and reconstructs the complete TCP-visible node
against the same SQLite file. Reconnection therefore preserves durable
messages, sequence continuity, and synchronization cursors without treating a
socket as OpenQSP identity.

Acceptance criteria:

- remote clients can perform every version 0.1 operation;
- reconnecting does not lose stored state or change synchronization semantics;
- connection state is not treated as OpenQSP identity;
- transport code does not duplicate protocol or domain rules;
- the same core scenarios can be executed through the Internet transport.

Production-grade authentication may remain a later milestone, but development authentication must be visibly marked as non-production.

---

## 8. Milestone 6 - APRS transport profile and simulator

**Status: deferred**

Objective: define, simulate and implement OpenQSP carriage over APRS after the node core is stable.

Required design work before implementation:

- text-safe encoding;
- fragmentation and reassembly;
- message correlation;
- APRS acknowledgement interaction;
- retry timing and limits;
- duplicate suppression;
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
- successful exchange is demonstrated locally through the simulator;
- successful exchange is then demonstrated over APRS-IS before testing over RF.

APRS must remain a transport adapter and must not redefine OpenQSP object or protocol semantics.

---

## 9. Milestone 7 - User application

**Status: deferred**

Objective: implement the first user-facing client after the server and at least one transport are usable.

Expected minimum features:

- callsign identity configuration;
- private-message inbox and sending;
- bulletin-header list;
- bulletin download;
- local persistence;
- independent message and bulletin synchronization cursors;
- clear delivery and error states.

The application platform and framework do not affect the Core protocol.

---

## 10. Test and laboratory layers

OpenQSP development uses four complementary levels:

1. **Unit tests** - verify codec, storage and server functions in isolation.
2. **Protocol vectors** - verify exact binary compatibility with `09-protocol-examples.md`.
3. **Laboratory and scenario tools** - emulate users, workflows and later unreliable transports.
4. **Real transports** - verify the same behaviour over Internet, APRS-IS and eventually RF.

Laboratory tools must reuse production protocol code wherever possible. They must not become an alternative implementation of OpenQSP semantics.

---

## 11. Later extensions

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

## 12. Immediate implementation order

The next development work should proceed in this order:

1. protocol package, codec and automated tests;
2. `frame_tool.py` using the production codec;
3. SQLite schema and storage implementation plus storage scenarios;
4. minimum server-core request handler;
5. `client_sim.py` and multi-user scenarios;
6. automated local end-to-end tests;
7. first Internet transport and remote simulator mode;
8. APRS transport profile, `aprs_sim.py`, APRS-IS and finally RF.

Work may overlap where dependencies permit, but a milestone must satisfy its acceptance criteria before it is considered complete.

---

## 13. Minimum server release definition

The first minimum server release is complete when Milestones 1 through 4 are
complete. **That condition is now satisfied:** Milestones 1 through 4 are
complete, delivering the minimum local server/core release.

It must demonstrate that:

- a node can start with an empty persistent database;
- one authenticated user can submit a private message;
- the node stores it durably and handles retries idempotently;
- the intended recipient can retrieve it incrementally;
- other users cannot retrieve it;
- bulletin headers and bodies can be retrieved;
- protocol errors are deterministic;
- state survives restart;
- the same behaviour can be reproduced through maintained development tools and automated scenarios;
- all required behaviour is covered by automated tests.

A real APRS adapter, graphical application and production authentication are not required for this first release.

The completed release includes the protocol codec, persistent store, minimum
server core, multi-user end-to-end workflows, synchronization reliability,
synchronization, restart persistence, bulletin retrieval, and the development
TCP Internet transport. It intentionally has no APRS transport,
production-grade authentication, or final user application; those belong to
later milestones.
