# 05 - Roadmap

## Purpose

This document defines the planned evolution of OpenQSP through small, verifiable milestones.

A milestone is complete only when its stated acceptance criteria are satisfied. Design documents describe the required behaviour; implementation milestones prove that behaviour with working code and automated tests.

---

## 1. Current project phase

OpenQSP is transitioning from protocol design to implementation of the minimum viable node.

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

The next active milestone is the minimum server core.

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
- synchronization uses node-local monotonic sequences;
- duplicate, conflict, durability and cursor rules defined;
- limits and errors defined;
- reference binary vectors available.

---

## 3. Milestone 1 - Protocol codec

**Status: planned**

Objective: implement a transport-independent encoder and decoder for OpenQSP Core frames.

Scope:

- parse and validate the 4-byte Core header;
- encode and decode every version 0.1 request and response;
- enforce field limits and UTF-8 rules;
- expose typed in-memory request and response objects;
- reject malformed, truncated and oversized frames safely.

Acceptance criteria:

- every valid vector in `09-protocol-examples.md` decodes to the expected fields;
- encoding those fields reproduces the exact canonical bytes;
- every documented invalid vector is rejected with the expected error category;
- unknown versions, operations and flags are handled as specified;
- tests cover all operation types and boundary sizes;
- the codec has no dependency on sockets, APRS, WebSocket or database code.

---

## 4. Milestone 2 - Persistent object store

**Status: planned**

Objective: implement the storage contract defined in `08-node-storage.md`.

Initial implementation target:

- SQLite;
- explicit schema migrations;
- transactional writes;
- separate message and bulletin sequence spaces;
- indexes for mailbox and bulletin retrieval.

Acceptance criteria:

- a new message is stored atomically and receives a stable sequence;
- identical retries return `ALREADY_STORED` without creating duplicates;
- identifier reuse with different content returns `CONFLICT`;
- object identifiers are unique across all object types;
- messages can be retrieved by recipient and `since` cursor;
- bulletin headers can be retrieved incrementally;
- complete bulletins can be retrieved by identifier;
- data and sequence state survive process restart;
- cursor and pagination behaviour matches `03-protocol.md` and `08-node-storage.md`;
- automated tests cover rollback and restart scenarios.

---

## 5. Milestone 3 - Minimum server core

**Status: planned**

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

Acceptance criteria:

- the authenticated callsign is used as message author;
- the client cannot inject a different author;
- every supported request produces the correct `ACK`, object frames, `END` or `ERROR` response;
- one user cannot retrieve another user's private messages;
- partial multi-item responses never advance a client cursor without `END`;
- malformed frames do not crash or corrupt the node;
- responses reproduce the binary protocol exactly;
- all tests run without a network connection.

Completion of this milestone defines the first functioning OpenQSP node core.

---

## 6. Milestone 4 - Local reference client and end-to-end test

**Status: planned**

Objective: prove the complete version 0.1 workflow with a small command-line client or test harness.

Acceptance criteria:

- two test users can exchange private messages through one node;
- a sender can safely retry after losing an acknowledgement;
- the recipient can synchronize messages incrementally;
- bulletin headers and complete bulletins can be retrieved;
- synchronization resumes correctly after client and node restarts;
- the entire workflow is exercised by an automated end-to-end test.

This client is a development tool, not the final user application.

---

## 7. Milestone 5 - Internet transport

**Status: deferred until the server core is complete**

Objective: expose the minimum node through one simple Internet transport.

The exact choice between TCP, HTTP, WebSocket or another framing method will be made when implementation begins. The transport must provide the core with:

- one complete OpenQSP frame;
- one authenticated or development-authenticated callsign;
- a way to return one or more response frames.

Acceptance criteria:

- remote clients can perform every version 0.1 operation;
- reconnecting does not lose stored state or change synchronization semantics;
- connection state is not treated as OpenQSP identity;
- transport code does not duplicate protocol or domain rules.

Production-grade authentication may remain a later milestone, but development authentication must be visibly marked as non-production.

---

## 8. Milestone 6 - APRS transport profile

**Status: deferred**

Objective: define and implement OpenQSP carriage over APRS after the node core is stable.

Required design work before implementation:

- text-safe encoding;
- fragmentation and reassembly;
- message correlation;
- APRS acknowledgement interaction;
- retry timing and limits;
- duplicate suppression;
- channel rate control;
- proactive delivery while the user is locally active.

Acceptance criteria will include successful exchange over APRS-IS before testing over RF.

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

## 10. Later extensions

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

## 11. Immediate implementation order

The next development work should proceed in this order:

1. protocol codec and tests;
2. SQLite schema and storage implementation;
3. minimum server-core request handler;
4. local reference client and end-to-end tests;
5. first Internet transport;
6. APRS transport profile and implementation.

Work may overlap where dependencies permit, but a milestone must satisfy its acceptance criteria before it is considered complete.

---

## 12. Minimum server release definition

The first minimum server release is complete when Milestones 1 through 4 are complete.

It must demonstrate that:

- a node can start with an empty persistent database;
- one authenticated user can submit a private message;
- the node stores it durably and handles retries idempotently;
- the intended recipient can retrieve it incrementally;
- other users cannot retrieve it;
- bulletin headers and bodies can be retrieved;
- protocol errors are deterministic;
- state survives restart;
- all required behaviour is covered by automated tests.

A real APRS adapter, graphical application and production authentication are not required for this first release.