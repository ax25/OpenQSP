# Milestone 6 — Production identity, sessions and node capabilities

## Purpose

This document is the implementation specification and acceptance contract for **Milestone 6 (M6)** of OpenQSP.

`design/05-roadmap.md` remains the high-level project roadmap. This document expands M6 into a concrete, autonomous engineering task suitable for execution by Codex or another implementation agent.

The implementation agent is expected to inspect the current repository, plan the work, implement all feasible parts of M6, run and repair tests, update documentation, perform a final self-review, and deliver one reviewable pull request.

The agent must not require human approval between M6 subtasks.

---

## 1. Milestone objective

Replace development-only callsign identification with a production-capable identity/session boundary and define how a client discovers what a node can do before APRS transport work begins.

M6 must establish shared application semantics that remain independent from TCP, APRS, or any future transport.

The completed milestone must provide:

- callsign + password account authentication for normal Internet access;
- a documented offline-client policy;
- authenticated session lifecycle independent from any particular transport;
- explicit separation between OpenQSP user identity and transport connection state;
- server-initiated delivery for active clients;
- ACTIVE/INACTIVE or equivalent runtime presence semantics;
- capability/service discovery;
- deterministic authorization and unsupported-operation behaviour.

---

## 2. Source of truth and required repository reading

Before implementation, inspect the current repository and read at minimum:

- `README.md`;
- `design/01-architecture.md`;
- `design/02-domain.md`;
- `design/03-protocol.md`;
- `design/04-transports.md`;
- `design/05-roadmap.md`;
- `design/06-object-model.md`;
- `design/07-client-node-protocol.md`;
- `design/08-node-storage.md`;
- `design/09-protocol-examples.md`;
- `tools/README.md`;
- the current protocol implementation;
- `ServerCore`;
- the TCP server;
- the reference TCP client;
- scenario tooling/environment code;
- current automated tests.

The current repository state is authoritative.

Do not resurrect concepts intentionally removed by the scoped-sequence architecture refactor.

In particular, do not reintroduce:

- globally unique client-generated message IDs;
- Core-level retry IDs;
- Core-level APRS acknowledgement semantics;
- global private-message sequences;
- transport connection state as OpenQSP identity.

Private-message sequences remain recipient-mailbox-local `u32` values.

Bulletin sequences remain node-local `u32` values.

Transport reliability remains separate from Core object identity.

---

## 3. Autonomous execution contract

The implementation agent must:

1. inspect the repository before changing code;
2. produce its own internal dependency plan;
3. execute the complete milestone without requesting approval between subtasks;
4. run focused tests continuously during implementation;
5. diagnose and repair failures rather than stopping after the first failure;
6. update implementation, tests and documentation together;
7. perform a second-pass self-review before final delivery;
8. run the full quality gates before declaring M6 complete;
9. create one final pull request for human review;
10. never merge the final M6 pull request into `main` autonomously.

When multiple designs are possible, prefer:

1. the smallest coherent architecture;
2. preservation of existing behaviour;
3. transport independence;
4. testability;
5. explicit documented semantics;
6. minimal speculative abstraction;
7. no APRS-specific implementation in M6.

If a repository inconsistency is directly relevant to M6, fix it.

If it is unrelated, do not expand scope unnecessarily; document it in the final pull request instead.

---

## 4. Branch and delivery strategy

The autonomous M6 implementation should start from current `main` and use one milestone branch, preferably:

`codex/m6-production-identity-sessions-capabilities`

All M6 work must ultimately be integrated into that branch.

Temporary branches, worktrees or additional agents may be used internally when useful, but their results must be integrated back into the milestone branch by the implementation agent.

The final deliverable is one pull request:

- head: `codex/m6-production-identity-sessions-capabilities`;
- base: `main`.

Do not merge the pull request automatically.

Logical commits are encouraged. A reasonable structure is:

- M6 identity/account foundation;
- M6 authenticated session boundary;
- M6 TCP authentication integration;
- M6 proactive delivery/presence;
- M6 capability discovery;
- M6 conformance/tests/docs.

These commit boundaries are guidance, not a requirement.

---

## 5. Architecture constraints

Maintain this boundary:

```text
Transport
    ↓
Authentication / Session boundary
    ↓
OpenQSP application / ServerCore
    ↓
Persistent stores
```

### Transport layer

Transport adapters may own:

- sockets/connections;
- byte movement;
- transport framing;
- transport-specific connection setup and teardown.

Transport adapters must not own application identity semantics.

### Authentication/session layer

Authentication/session code may own:

- account credential verification;
- authenticated callsign context;
- runtime session lifecycle;
- active/inactive state;
- server-initiated outbound delivery routing;
- deterministic session cleanup.

It must not own message/bulletin persistence rules.

### Application/Core layer

`ServerCore` remains responsible for OpenQSP application operations and authorization decisions appropriate to those operations.

`ServerCore` must not directly depend on TCP classes.

### Storage layer

Storage remains responsible for durable state.

Account persistence may use dedicated storage/schema structures, but message and bulletin storage semantics must remain unchanged unless a required migration is explicitly justified.

### Explicitly out of scope

Do not introduce:

- APRS fragmentation;
- APRS reassembly;
- APRS ACK/retry logic;
- APRS duplicate suppression;
- RF timing/rate control;
- final M8 user application behaviour.

Those belong to later milestones.

---

## 6. M6.1 — Identity, authentication and account persistence

Implement production-capable account authentication based on:

`callsign + password`

### Requirements

- one OpenQSP account identity per normalized base callsign;
- reuse existing OpenQSP callsign normalization and validation semantics;
- passwords must never be stored in plaintext;
- use a modern salted password derivation mechanism available without unnecessary external infrastructure;
- verification should avoid timing-sensitive direct secret comparison where applicable;
- authentication failure must not disclose whether the callsign exists or the password was incorrect;
- accounts must survive node restart;
- account/credential storage must remain distinct from message and bulletin object identity;
- create a controlled account-provisioning mechanism suitable for development and tests;
- do not invent public self-registration unless current architecture clearly requires it.

For v0.1, account provisioning may remain a node-administration concern.

### Required tests

- account creation;
- successful authentication;
- wrong password;
- unknown user;
- duplicate normalized callsign;
- invalid callsign;
- persistence across restart;
- stored password representation does not contain the plaintext password;
- malformed credential input is rejected safely.

---

## 7. M6.2 — Transport-independent authenticated session boundary

Introduce or complete a proper application/session abstraction between transports and Core.

A session represents authenticated OpenQSP runtime identity.

A session is **not** a TCP socket.

### Required session properties

The abstraction must support enough state/behaviour for:

- authenticated callsign;
- lifecycle;
- active/inactive state or equivalent;
- server-initiated outbound delivery;
- deterministic cleanup;
- simultaneous sessions;
- future reuse by APRS or another transport without moving application rules into the transport.

Transport adapters should authenticate and establish/bind a session.

Core should receive authenticated identity through this boundary rather than deriving identity directly from TCP syntax.

### Required tests

- authenticated identity reaches Core;
- reconnecting through a different TCP connection preserves the same OpenQSP account identity;
- closing a session cleans runtime state;
- simultaneous sessions are safe;
- multiple sessions for one callsign behave deterministically;
- different users remain isolated;
- transport connection and OpenQSP identity are demonstrably distinct concepts.

---

## 8. M6.3 — Production TCP authentication

Replace the current development-only TCP `CALLSIGN <callsign>` identification path as the normal production authentication mechanism.

Design a bounded authentication exchange appropriate to the existing simple TCP transport.

### Requirements

- authenticate with callsign + password;
- bound all authentication input sizes;
- malformed authentication must not crash or poison the server;
- unauthenticated clients cannot issue normal Core operations;
- failed authentication rejects/closes predictably;
- authenticated sessions are created only after credential verification;
- OpenQSP Core frames remain transport-independent;
- update the reference TCP client to use production authentication.

The old development-only handshake may either:

- be removed; or
- remain behind an explicit development/test-only option.

It must never silently remain the production authentication path.

### Required tests

- successful production TCP login;
- invalid password rejection;
- unknown user rejection;
- malformed login rejection;
- Core operation before authentication is rejected;
- authenticated requests use the authenticated account identity;
- reconnect and authenticate again successfully;
- development-only authentication, if retained, is explicitly gated and documented.

---

## 9. M6.4 — Presence and server-initiated delivery

Implement shared semantics for proactive/server-initiated delivery.

An authenticated active client should be capable of receiving relevant newly available data without continuously polling.

At minimum, support the private-message use case.

Bulletin proactive notification may be implemented if it fits cleanly with existing protocol and architecture.

### Critical invariant

**Server-initiated frames must never accidentally satisfy, complete or corrupt a normal request/response exchange.**

Use existing `UNSOLICITED` protocol semantics where appropriate rather than introducing a parallel incompatible mechanism.

### Define explicitly

- when a session becomes ACTIVE;
- when activity is refreshed;
- when a session becomes INACTIVE;
- how disconnect affects presence;
- how multiple sessions for one callsign behave;
- which events are eligible for proactive delivery;
- what happens when outbound proactive delivery fails;
- whether and how inactive sessions are retained for any period.

Presence is runtime/session state, not persistent OpenQSP identity.

Durable synchronization remains authoritative.

Push is an optimization for active clients, not a substitute for mailbox synchronization.

### Required tests

- active recipient receives server-initiated delivery;
- a normal request can occur concurrently with unsolicited delivery;
- unsolicited frames never complete an outstanding normal request;
- inactive/disconnected recipient does not cause blocking or corruption;
- reconnect + normal synchronization recovers durable data;
- failed proactive delivery does not lose the durable message;
- multiple users remain isolated;
- multiple active sessions for the same account follow documented semantics.

---

## 10. M6.5 — Node capability/service discovery

A client must be able to discover what the node currently supports.

This should allow a future user application to adapt available actions/UI to a node instead of hardcoding every possible service.

Implement the smallest useful capability-discovery mechanism compatible with the existing OpenQSP protocol architecture.

### Expected discoverable capabilities

Advertise only features that actually exist, such as, when applicable:

- private messaging;
- bulletin listing;
- bulletin retrieval;
- proactive/server-initiated delivery;
- other implemented v0.1 node services.

Do not advertise planned but unimplemented capabilities.

### Requirements

Capabilities must be:

- deterministic;
- machine-readable;
- protocol-version coherent;
- easy for the reference client to query;
- sufficient for a future client UI to enable/disable available actions.

Do not design a large plugin ecosystem for M6.

If a new Core request/response operation is needed, update consistently:

- protocol constants;
- protocol models;
- codec;
- exports;
- validation;
- canonical vectors;
- protocol documentation;
- reference client;
- CLI;
- tests.

### Required tests

- capability query succeeds for an authenticated client;
- returned capabilities match actual node behaviour;
- unimplemented services are not advertised;
- wire encoding/decoding round-trips exactly;
- canonical protocol vector coverage exists for any new frame;
- the reference client can use the capability response.

---

## 11. M6.6 — Authorization and deterministic errors

Authenticated identity and capability discovery must lead to deterministic authorization/error behaviour.

At minimum distinguish correctly between cases such as:

- malformed request;
- unauthenticated access;
- unsupported operation/capability;
- unauthorized operation;
- missing resource;
- rejected request.

Reuse existing protocol error semantics where appropriate.

Extend the protocol error set only when needed and document any extension.

Do not leak:

- credential details;
- password-verification details;
- raw internal exceptions;
- implementation stack traces.

### Required tests

- unauthenticated access maps deterministically;
- unsupported operation maps deterministically;
- unauthorized operation maps deterministically where applicable;
- malformed input maps deterministically;
- missing resource behaviour remains correct;
- internal authentication/storage failures are not exposed as sensitive detail.

---

## 12. M6.7 — Offline-client policy

M6 does not implement the final user application. That belongs to M8.

M6 must nevertheless define the offline policy that M8 will follow.

Document that:

- successful server authentication establishes online identity/session;
- lack of Internet connectivity must not prevent a previously configured client application from opening;
- locally cached content/state may be inspected offline;
- operations requiring the node remain pending/unavailable until connectivity/authentication returns;
- local offline application access is not equivalent to server authentication;
- any future cached credentials/tokens require explicit security semantics;
- APRS authentication behaviour is not invented in M6;
- reconnecting and re-authenticating must preserve the same OpenQSP account identity.

Do not build the M8 application in this milestone.

---

## 13. Storage and migration requirements

Inspect the current SQLite migration strategy before making account-persistence changes.

If account persistence requires schema changes:

- add an explicit ordered migration;
- make migration transactional where the repository's migration model requires it;
- preserve existing messages and bulletins;
- preserve mailbox and bulletin sequence state;
- do not silently destroy existing development databases;
- cover migration and rollback/restart behaviour in tests;
- reject unsupported future schema versions as the current storage layer does.

Existing application data must remain valid after upgrading to M6.

---

## 14. Reference client and CLI

Update the existing reference TCP client so M6 can be exercised end-to-end.

The reference client should support at least:

- authenticated connect using callsign + password;
- normal private messaging;
- message synchronization;
- bulletin synchronization/retrieval as already supported;
- capability query;
- observing server-initiated events;
- reconnecting cleanly.

Update the interactive CLI as needed.

The CLI remains a development/reference tool, not the final M8 user application.

---

## 15. Required end-to-end conformance workflow

Create or extend an integrated M6 conformance test that exercises the production stack.

At minimum prove this flow:

```text
account provision
→ authenticated TCP connection
→ capability query
→ two users authenticate
→ user A sends private message to user B
→ active B receives server-initiated delivery/event
→ B performs normal synchronization
→ disconnect
→ node restart
→ authenticate again
→ synchronization state remains coherent
```

The workflow must use real production components as applicable:

- production codec;
- TCP adapter;
- account/authentication layer;
- session layer;
- `ServerCore`;
- SQLite persistence;
- reference/development client interfaces.

Do not manually manipulate private-message rows to fake the workflow.

Development-only account provisioning or bulletin seeding is acceptable as test setup when clearly isolated from production protocol semantics.

---

## 16. Test strategy

Add unit, integration and end-to-end coverage.

Preserve existing tests unless behaviour is intentionally superseded by M6.

If an old test is obsolete, replace its useful behavioural coverage rather than simply deleting it.

### Authentication coverage

- [ ] account creation;
- [ ] valid login;
- [ ] invalid password;
- [ ] unknown callsign;
- [ ] malformed login;
- [ ] restart persistence;
- [ ] no plaintext password storage;
- [ ] unauthenticated Core access rejection.

### Session coverage

- [ ] login creates authenticated session;
- [ ] disconnect cleanup;
- [ ] reconnect;
- [ ] concurrent clients;
- [ ] same user with multiple sessions;
- [ ] different users isolated;
- [ ] TCP connection is not identity.

### Proactive-delivery coverage

- [ ] active recipient receives event;
- [ ] inactive recipient retrieves later via normal sync;
- [ ] unsolicited delivery cannot satisfy normal request;
- [ ] disconnect during push does not corrupt durable state;
- [ ] failed push does not lose message;
- [ ] durable synchronization remains authoritative.

### Capability coverage

- [ ] capability query succeeds;
- [ ] advertised capabilities match implemented features;
- [ ] unsupported operation behaviour is deterministic;
- [ ] new protocol vectors round-trip exactly;
- [ ] reference client consumes capability response.

### End-to-end coverage

- [ ] authenticated two-user TCP workflow;
- [ ] proactive delivery;
- [ ] normal synchronization after proactive delivery;
- [ ] reconnect;
- [ ] node restart;
- [ ] persistent account and message state;
- [ ] post-restart re-authentication;
- [ ] coherent synchronization after restart.

---

## 17. Quality gates

Before declaring M6 complete, run all feasible repository quality checks.

At minimum:

1. run the complete server/repository test suite;
2. run focused M6 tests;
3. run lint/static checks already used by the repository where available;
4. run Python compilation sanity checks (`python -m compileall` or equivalent);
5. run `git diff --check`;
6. verify no plaintext password storage exists;
7. search documentation/code for stale claims that `CALLSIGN <callsign>` is production authentication;
8. search for accidental TCP dependencies in Core/domain/storage layers;
9. search for APRS-specific logic accidentally introduced into authentication/session/application code;
10. verify protocol documentation and implementation agree;
11. verify advertised capabilities match actual implementation;
12. verify no known test regression remains.

Do not declare completion with known failing tests unless execution is blocked by a genuine external environment limitation that cannot reasonably be worked around.

If dependency installation is blocked, use the repository's established `PYTHONPATH` testing method where possible and document the limitation.

---

## 18. Security review checklist

Before final delivery, inspect specifically for:

- [ ] plaintext password persistence;
- [ ] predictable/unsalted password hashing;
- [ ] authentication bypass paths;
- [ ] callsign normalization inconsistencies;
- [ ] different error messages revealing unknown-user vs wrong-password state;
- [ ] unbounded authentication input;
- [ ] session fixation or accidental session reuse;
- [ ] identity derived from socket state;
- [ ] locks held during potentially blocking network writes;
- [ ] unsafe concurrent session registry access;
- [ ] sensitive exceptions sent to clients;
- [ ] accidental credential logging;
- [ ] tests containing production-like shared secrets unnecessarily.

Fix discovered issues before final delivery.

---

## 19. Concurrency and unsolicited-delivery review checklist

Review specifically for:

- [ ] request/response correlation race conditions;
- [ ] unsolicited frames completing normal requests;
- [ ] concurrent writes corrupting frame boundaries;
- [ ] registry locks held while sending network data;
- [ ] stale active sessions surviving disconnect indefinitely;
- [ ] failed delivery removing durable mailbox state;
- [ ] duplicate active sessions causing inconsistent behaviour;
- [ ] deadlock between Core, session registry and transport send paths.

The documented runtime semantics must match the implemented behaviour.

---

## 20. Documentation updates

Inspect and update as applicable:

- `README.md`;
- `design/01-architecture.md`;
- `design/02-domain.md`;
- `design/03-protocol.md`;
- `design/04-transports.md`;
- `design/05-roadmap.md`;
- `design/06-object-model.md`;
- `design/07-client-node-protocol.md`;
- `design/08-node-storage.md`;
- `design/09-protocol-examples.md`;
- `tools/README.md`;
- this document when implementation decisions clarify or refine its checklist without weakening its requirements.

Do not modify documentation merely to create churn.

Document actual implemented behaviour.

If all mandatory M6 acceptance criteria are satisfied, update `design/05-roadmap.md` so:

- Milestone 6 becomes `complete`;
- Milestone 7 becomes the next planned/active milestone as appropriate.

If material requirements remain incomplete, do **not** falsely mark M6 complete.

Document precisely what remains.

---

## 21. M6 acceptance matrix

M6 is complete only when all mandatory items below are satisfied.

### Identity and authentication

- [ ] persistent OpenQSP account storage exists;
- [ ] one normalized base callsign maps to one account identity;
- [ ] callsign + password authentication works;
- [ ] passwords are not stored in plaintext;
- [ ] credential verification follows documented security semantics;
- [ ] account data survives restart;
- [ ] authentication failure does not reveal unknown-user vs wrong-password distinction;
- [ ] controlled account provisioning exists for development/tests/administration.

### Session architecture

- [ ] authenticated session abstraction is transport-independent;
- [ ] authenticated callsign reaches Core through the session boundary;
- [ ] TCP connection state is not OpenQSP identity;
- [ ] reconnecting does not create a new OpenQSP account identity;
- [ ] session cleanup is deterministic;
- [ ] concurrent sessions are safe;
- [ ] multiple sessions for one callsign have documented semantics.

### Production TCP access

- [ ] normal TCP access uses production callsign + password authentication;
- [ ] development-only `CALLSIGN` identification is removed or explicitly gated;
- [ ] unauthenticated clients cannot issue normal Core operations;
- [ ] authentication exchange is bounded and validated;
- [ ] reference TCP client supports production authentication.

### Presence and proactive delivery

- [ ] ACTIVE/INACTIVE or equivalent semantics are implemented and documented;
- [ ] an active recipient can receive server-initiated private-message delivery/event;
- [ ] server-initiated frames use coherent unsolicited semantics;
- [ ] unsolicited frames cannot satisfy a normal request;
- [ ] failed/inactive push does not lose durable mailbox data;
- [ ] normal synchronization remains authoritative;
- [ ] reconnect recovers all durable data correctly.

### Capabilities

- [ ] authenticated client can query node capabilities;
- [ ] capability representation is deterministic and machine-readable;
- [ ] only implemented capabilities are advertised;
- [ ] reference client exposes capability query;
- [ ] CLI can display/use discovered capabilities where appropriate;
- [ ] protocol vectors/docs are updated for any new frames.

### Authorization and errors

- [ ] unauthenticated behaviour is deterministic;
- [ ] unsupported operation behaviour is deterministic;
- [ ] unauthorized operation behaviour is deterministic where applicable;
- [ ] malformed request behaviour remains deterministic;
- [ ] missing-resource behaviour remains correct;
- [ ] sensitive internal/authentication details are not exposed.

### Offline policy

- [ ] offline-client policy is documented;
- [ ] offline application access is explicitly separated from server authentication;
- [ ] cached local state behaviour is defined at policy level;
- [ ] APRS authentication is explicitly deferred rather than invented in M6.

### Compatibility and persistence

- [ ] existing messages/bulletins survive any required migration;
- [ ] sequence semantics remain unchanged;
- [ ] account persistence survives restart;
- [ ] existing supported database upgrade path remains explicit and tested.

### Conformance

- [ ] full M6 end-to-end workflow exists;
- [ ] full test suite passes;
- [ ] focused M6 tests pass;
- [ ] static/lint/compile checks pass where available;
- [ ] documentation agrees with implementation;
- [ ] final self-review finds no known blocking defect.

---

## 22. Final self-review

Before opening the final pull request, review the complete M6 diff as if reviewing another engineer's work.

Look for:

- security mistakes;
- authentication bypasses;
- credential leakage;
- session races;
- locks held during network I/O;
- identity/socket coupling;
- unsolicited/request correlation bugs;
- durable synchronization regressions;
- SQLite migration problems;
- protocol incompatibilities;
- inconsistent errors;
- advertised but unimplemented capabilities;
- undocumented protocol changes;
- unnecessary abstraction;
- APRS-specific logic leaking into shared layers;
- useful test coverage removed without replacement.

Fix issues found during this review.

Then rerun the quality gates.

---

## 23. Final pull request requirements

Create one final PR to `main`.

Suggested title:

`M6 — Production identity, sessions and node capabilities`

The PR body should contain:

### Summary

What M6 implements.

### Architecture

Identity, account storage, session boundary, presence/push, capability discovery and transport separation.

### Protocol changes

Exact new operations, frames and error codes, if any.

### Storage changes

Schema, migration and account-storage changes.

### Authentication

How credentials are stored and verified.

### Session lifecycle

Creation, ACTIVE/INACTIVE semantics, cleanup and multiple-session behaviour.

### Proactive delivery

How unsolicited delivery works and how request/response correlation remains safe.

### Capabilities

What is discoverable and how.

### Offline policy

What M6 defines for future M8 behaviour.

### Tests

Exact commands and results.

### Compatibility

Migration and compatibility considerations.

### Remaining limitations

Anything deliberately deferred to M7/M8 or externally blocked.

### Milestone status

Explicitly state whether every mandatory M6 acceptance criterion is satisfied.

Do not merge the PR automatically.

---

## 24. Definition of Done

M6 is not complete merely because implementation code exists.

The milestone is complete when the repository contains the most complete coherent implementation reasonably achievable of:

- production account authentication;
- persistent accounts;
- transport-independent authenticated sessions;
- production TCP authentication;
- runtime presence;
- safe server-initiated delivery;
- capability discovery;
- deterministic authorization/errors;
- offline-client policy;
- migration/compatibility handling;
- reference client support;
- comprehensive automated tests;
- updated architecture/protocol/tool documentation.

Every mandatory acceptance-matrix item must either:

- be satisfied and supported by implementation/tests; or
- have a genuine external blocker documented explicitly.

Known implementation defects, failing tests, incomplete internal refactors, or unimplemented requirements are not external blockers.

The final human review boundary is the M6 pull request to `main`.

---

## 25. Minimal Codex execution prompt

A Codex task may use this document with a short execution prompt such as:

```text
Read design/tasks/M6-implementation-spec.md in full.

You are responsible for implementing the complete Milestone 6 described there autonomously.
Treat that file as the implementation specification and acceptance contract.

Inspect the current repository before implementation and reconcile the specification with the current codebase.
Complete all feasible implementation, tests, documentation, migrations, self-review and final PR work described in the specification.

Do not request human approval between subtasks.
Do not stop after one subtask.
Repair test failures and continue.
Do not merge into main.

If a requirement admits several designs, choose the smallest coherent solution consistent with the existing architecture and document important decisions in the final PR.

Deliver the most complete M6 implementation possible in one milestone branch and one final PR to main.
```
