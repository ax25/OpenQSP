# Milestone 7 — APRS transport profile and simulator

## Purpose

This document is the implementation specification and acceptance contract for **Milestone 7 (M7)** of OpenQSP.

`design/05-roadmap.md` remains the high-level project roadmap. This document expands M7 into a concrete, autonomous engineering task suitable for execution by Codex or another implementation agent.

The implementation agent is expected to inspect the current repository, plan the work, implement all feasible parts of M7, run and repair tests, update documentation, perform a final self-review, and deliver one reviewable pull request.

The agent must not require human approval between M7 subtasks.

---

## 1. Milestone objective

Implement a production-shaped APRS transport adapter for OpenQSP without changing OpenQSP Core object identity, storage semantics, or the binary application protocol.

M7 must define and implement how one complete OpenQSP binary frame is carried through APRS messaging, including:

- text-safe encoding;
- fragmentation and reassembly;
- APRS message-ID acknowledgement handling;
- fragment retransmission;
- request/response transaction correlation;
- peer-scoped duplicate suppression;
- replay of prior Core results when a complete request is retried;
- bounded transport state;
- channel-aware rate control;
- APRS-local activity and proactive delivery;
- a deterministic APRS simulator with fault injection;
- APRS-IS integration after local simulator conformance passes.

The completed milestone must demonstrate this path:

```text
OpenQSP frame
→ APRS encode
→ fragmentation
→ APRS message packets
→ loss/reorder/duplicate/retry behaviour
→ reassembly
→ identical OpenQSP frame
→ ServerCore
→ response frame(s)
→ APRS carriage back to the client
```

APRS remains a transport adapter. It must not redefine application objects or introduce transport IDs into persistent OpenQSP data.

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
- `design/tasks/M6-implementation-spec.md`;
- `tools/README.md`;
- the current protocol constants, models and codec;
- `ServerCore`;
- the M6 account/session implementation;
- the TCP server and reference TCP client;
- scenario tooling/environment code;
- all current automated tests.

The current repository state is authoritative.

In particular, preserve these existing invariants:

- OpenQSP protocol version remains `0x01` unless a real incompatibility requires a version change;
- `MAX_PAYLOAD_SIZE` remains 255 and `MAX_FRAME_SIZE` remains 259 unless separately justified outside this milestone;
- private-message sequences remain recipient-mailbox-local `u32` values;
- bulletin sequences remain node-local `u32` values;
- `STORED` confirms durable Core/database acceptance and is not an APRS ACK;
- APRS message IDs are transport-local and must never become `Message`, `Bulletin`, storage, or Core IDs;
- retry and duplicate suppression remain transport concerns;
- the APRS service identity remains `OPENQSP`;
- an APRS SSID is transport addressing only and does not create a distinct OpenQSP identity;
- durable synchronization remains authoritative even when proactive delivery exists.

Do not resurrect intentionally removed concepts such as globally unique client-generated message IDs or Core-level retry identifiers.

---

## 3. Autonomous execution contract

The implementation agent must:

1. inspect the repository before changing code;
2. produce its own internal dependency plan;
3. execute the complete milestone without requesting approval between subtasks;
4. run focused tests continuously;
5. diagnose and repair failures rather than stopping at the first failure;
6. keep protocol, transport, tests, tools and documentation coherent;
7. perform a second-pass self-review before delivery;
8. run all quality gates before declaring M7 complete;
9. create one final pull request for human review;
10. never merge the final M7 pull request into `main` autonomously.

When multiple implementation choices are possible, prefer:

1. compatibility with existing APRS messaging behaviour;
2. the smallest deterministic transport state machine;
3. bounded memory and bounded retries;
4. preservation of existing OpenQSP Core semantics;
5. testability through deterministic simulation;
6. explicit failure behaviour;
7. minimum RF/channel occupancy;
8. no speculative multi-transport abstraction beyond what M7 needs.

If a repository inconsistency is directly relevant to M7, fix it. If unrelated, report it in the final PR rather than expanding scope.

---

## 4. Branch and delivery strategy

Start from current `main` and use one milestone branch, preferably:

`codex/m7-aprs-transport-profile-simulator`

All M7 work must ultimately be integrated into that branch.

Temporary worktrees or helper branches may be used internally, but the final deliverable is one pull request:

- head: `codex/m7-aprs-transport-profile-simulator`;
- base: `main`.

Do not merge automatically.

Logical commits are encouraged. A reasonable structure is:

- APRS carriage codec/profile;
- APRS fragmentation/reassembly;
- ACK/retry and duplicate suppression;
- simulator and fault injection;
- APRS adapter/Core integration;
- APRS activity/proactive delivery;
- APRS-IS integration;
- M7 conformance/tests/docs.

These boundaries are guidance, not a requirement.

---

## 5. Architecture constraints

Maintain this boundary:

```text
APRS / APRS-IS packet transport
        ↓
OpenQSP APRS carriage adapter
  - addressing
  - text-safe encoding
  - fragmentation/reassembly
  - APRS ACK/retry
  - duplicate suppression
  - transaction correlation
  - activity/rate state
        ↓
transport/session identity bridge
        ↓
ServerCore
        ↓
persistent stores
```

### APRS adapter may own

- APRS source/destination parsing;
- APRS message IDs;
- APRS `ack<ID>` handling;
- text-safe carriage encoding;
- fragmentation and reassembly;
- retransmission timers and limits;
- peer-scoped transaction IDs;
- duplicate-fragment suppression;
- replay cache for completed transport requests;
- APRS-local activity timers;
- outbound queueing and rate limiting;
- APRS-IS socket lifecycle and reconnect logic.

### APRS adapter must not own

- private-message storage semantics;
- bulletin storage semantics;
- mailbox sequence allocation;
- bulletin sequence allocation;
- Core authorization rules unrelated to APRS transport identity;
- persistent transport transaction IDs;
- application-level retry semantics;
- alternative OpenQSP frame formats.

### ServerCore must not

- parse APRS text;
- know fragment numbers;
- know APRS message IDs;
- implement APRS retry timers;
- persist APRS transaction state.

---

## 6. APRS identity and security boundary

### 6.1 Service identity

The OpenQSP APRS service identity is:

`OPENQSP`

For APRS-IS, the service connects using the normal verified APRS-IS login mechanism and may request:

`filter g/OPENQSP`

Deployment passcodes or secrets must never be committed to the repository.

### 6.2 User identity

For an inbound APRS message, use the packet source address as the APRS transport peer.

Normalize the source to the existing OpenQSP base-callsign identity before invoking Core. For example:

```text
EA3GNU-10 -> OpenQSP identity EA3GNU
EA3GNU-7  -> OpenQSP identity EA3GNU
```

The full APRS source including SSID remains available only for short-lived transport addressing and correlation.

### 6.3 Security semantics

M7 must explicitly document that APRS source callsigns are **transport-asserted, not cryptographically authenticated**.

Do not transmit an OpenQSP account password over APRS. Do not invent a replayable password/token scheme in this milestone.

An APRS-originated request is therefore lower-assurance than the password-authenticated Internet path introduced by M6.

For v0.1, the APRS adapter may bind the normalized APRS source callsign to the same OpenQSP identity used by Core. This does not imply that the radio transport proves legal ownership of that callsign.

Tests and documentation must make the limitation explicit rather than pretending APRS provides strong authentication.

Do not redesign cryptographic identity in M7.

---

## 7. APRS carriage profile v0.1

M7 must implement one canonical text carriage for complete OpenQSP binary frames.

### 7.1 Text-safe encoding

Encode the complete OpenQSP binary frame using **unpadded Base64url**:

- alphabet: `A-Z a-z 0-9 - _`;
- no whitespace;
- omit `=` padding on transmission;
- restore required padding before decoding;
- reject invalid alphabet or impossible encoded length;
- after decode, pass the resulting bytes through the existing production OpenQSP frame decoder/validation.

Do not create a second application codec.

### 7.2 Fragment text format

Each APRS message carrying an OpenQSP fragment must use this body before the native APRS message-ID suffix:

```text
Q1:<TTT>:<II>/<NN>:<DATA>
```

where:

- `Q1` identifies OpenQSP APRS carriage profile version 1;
- `TTT` is a 3-character uppercase base36 transport transaction ID;
- `II` is the 2-character uppercase base36 zero-based fragment index;
- `NN` is the 2-character uppercase base36 total fragment count;
- `DATA` is a contiguous chunk of the unpadded Base64url OpenQSP frame.

Example:

```text
Q1:0A7:00/03:AQEAEEUAAAA...
```

The normal APRS message number is appended using APRS message syntax and is not part of `DATA`, for example:

```text
Q1:0A7:00/03:AQEAEEUAAAA...{4F
```

### 7.3 Fixed DATA chunk size

Use a maximum `DATA` chunk size of **48 ASCII characters**.

Fragment the complete encoded Base64url string into chunks of at most 48 characters.

This deliberately leaves margin inside the APRS one-line message body for the carriage header and a short native APRS message ID.

The final fragment may contain fewer than 48 data characters.

### 7.4 Fragment count bound

The current OpenQSP maximum frame is 259 bytes, so the encoded form is small enough for a bounded number of APRS fragments.

The implementation must derive the required fragment count from the actual encoded length and reject impossible counts rather than allocating unbounded structures.

The v0.1 profile permits at most **16 fragments per OpenQSP frame**.

Any future OpenQSP frame that cannot fit within this bound is not transportable by APRS profile v0.1 and must fail deterministically at the APRS adapter boundary.

Do not change Core frame limits merely to accommodate APRS.

### 7.5 Transaction ID

`TTT` is transport-local and scoped to the full APRS peer address.

It must:

- use uppercase base36 `000` through `ZZZ`;
- roll over safely;
- avoid collision with currently active transactions for that peer;
- never be persisted in OpenQSP objects or database rows.

The same complete request retransmission must reuse the same transport transaction ID when the sender is intentionally retrying that transport transaction.

A new logical request should normally allocate a new transaction ID.

---

## 8. Native APRS message IDs and fragment ACKs

Each APRS fragment is itself an APRS message and must use a native APRS message ID so the receiving endpoint can acknowledge packet reception.

### Requirements

- allocate short peer-scoped native APRS message IDs;
- correlate `ack<ID>` only with the intended peer and pending outbound fragment;
- retransmission of the same fragment uses the same APRS message ID;
- ACK receipt completes transport delivery of that fragment only;
- APRS ACK never means OpenQSP `STORED`;
- an unexpected or stale ACK must be ignored safely;
- malformed ACK text must not reach Core;
- receiving a valid fragment must generate the appropriate native APRS ACK according to adapter policy even if the complete OpenQSP frame is not yet reassembled.

The implementation may use a compact rolling uppercase base36 message-ID space. The exact internal allocator representation is an implementation detail, but IDs must remain bounded and peer-scoped.

---

## 9. Fragment reassembly

Maintain bounded in-memory reassembly state keyed by:

```text
(full APRS source address, TTT)
```

A reassembly entry must track at minimum:

- expected total fragment count;
- received fragment indexes;
- fragment payloads;
- first-seen / last-seen time;
- completion state.

### Required behaviour

- fragments may arrive in any order;
- exact duplicate fragments are idempotent;
- duplicate fragment index with different `DATA` is a conflict and invalidates/rejects that transaction deterministically;
- inconsistent `NN` across fragments invalidates/rejects that transaction;
- indexes outside the declared range are rejected;
- a complete frame is assembled only after every index `00 .. NN-1` exists;
- concatenate `DATA` in fragment-index order;
- Base64url-decode exactly once after full reassembly;
- validate the complete binary OpenQSP frame using production codec logic;
- malformed completed frames are not sent to Core;
- incomplete entries expire after a configurable bounded timeout;
- expiration must release memory.

Never partially invoke Core.

---

## 10. Request transaction deduplication and Core-result replay

Fragment ACKs prevent many retransmissions but do not by themselves make a complete OpenQSP request exactly-once.

M7 therefore requires a short-lived completed-transaction cache keyed by:

```text
(full APRS peer address, TTT)
```

For each completed inbound request, cache enough information to determine whether a later retry is identical and, when appropriate, replay the already-produced Core response frames without invoking Core again.

### Required semantics

When a fully reassembled request `(peer, TTT)` is first seen:

1. validate the OpenQSP frame;
2. invoke Core exactly once;
3. capture the ordered Core response frame(s);
4. queue those response frame(s) for APRS carriage;
5. store a bounded replay-cache entry containing at minimum a digest or exact request bytes plus the Core response bytes.

When `(peer, TTT)` is received again:

- if the reassembled request bytes are identical, do **not** invoke Core again; replay the cached response frame(s);
- if the bytes differ, treat it as a transport transaction conflict and reject/drop deterministically;
- never infer duplicate application objects from content alone across different transaction IDs.

This mechanism is transport-local and short-lived.

It must not add persistent request IDs to Core or storage.

### Cache bounds

The replay cache must have:

- configurable TTL;
- configurable per-peer and/or global maximum entries;
- deterministic eviction;
- tests proving memory cannot grow without bound.

---

## 11. Retry policy

Implement deterministic configurable fragment retry behaviour.

Use conservative defaults suitable for laboratory and APRS-IS testing; keep timings configurable so RF policy can be tuned without changing Core.

Recommended default policy for M7 implementation:

- initial send immediately;
- ACK timeout: **8 seconds**;
- maximum transmission attempts per fragment: **3** total attempts;
- no busy-loop retries;
- preserve the same APRS message ID across attempts of one fragment;
- after the retry limit, mark that outbound OpenQSP transport transaction failed and release pending fragment state after any required bookkeeping.

The simulator must permit much shorter virtual/test timings without changing semantics.

Do not make Core persistence success depend on successful APRS response delivery.

A `SEND_MESSAGE` that reached Core and returned `STORED` remains stored even if the transport later fails to deliver the `STORED` response back to the sender.

If the sender retries the same APRS transport transaction ID, result replay must avoid a second Core invocation.

---

## 12. Outbound frame handling and response correlation

Core may return one or more OpenQSP response frames for one request.

The APRS adapter must preserve their order.

Each complete Core response frame is independently encoded and fragmented using the carriage profile.

The implementation needs an outbound transaction ID for each complete response frame. It must not assume that one APRS transport transaction maps to exactly one returned Core frame.

A request that yields a stream such as:

```text
MESSAGE
MESSAGE
END
```

must carry all response frames in that same application order.

The adapter may serialize response-frame delivery per peer to simplify correlation and channel occupancy. This is preferred for v0.1 over a complex concurrent streaming design.

Do not let fragments from later response frames cause the client to deliver those frames to the application before earlier response frames have completed.

---

## 13. Rate control and queueing

APRS is a shared, low-bandwidth channel. M7 must not emit unbounded bursts.

Implement a bounded outbound queue and configurable rate limiter.

The production-shaped default should ensure that APRS messages are spaced rather than emitted as a CPU-speed burst.

Recommended default minimum interval between originated APRS message packets to the same peer:

**2 seconds**

The simulator may override this to zero or virtual time for deterministic tests.

### Required behaviour

- queue capacity must be bounded;
- pending retries must participate in rate control;
- responses to explicit requests take priority over unsolicited/proactive traffic;
- transport ACKs may bypass normal application queue delay when required for correct APRS acknowledgement behaviour;
- proactive traffic must not starve direct responses;
- queue overflow must fail/drop according to explicit documented policy rather than grow memory indefinitely.

Do not encode RF-specific assumptions such as a fixed digipeater path into Core.

---

## 14. APRS-local activity and proactive delivery

Reuse the policy already described in `design/04-transports.md`.

APRS activity is local transport state, not M6 TCP session presence.

### Active state

A peer becomes APRS-active when the adapter receives and successfully validates a complete OpenQSP client request from that peer.

Any subsequent valid client request refreshes the APRS activity timer.

Malformed fragments, unrelated APRS packets, node-originated frames and pure transport ACKs do not refresh OpenQSP user activity.

### Timeout

Use a configurable activity timeout.

Recommended default for implementation/testing:

**10 minutes**

Tests must use injected/virtual time rather than sleeping for real minutes.

### Proactive delivery

While APRS-active, the user may receive eligible unsolicited private-message `MESSAGE` frames using the existing OpenQSP `UNSOLICITED` flag.

Requirements:

- proactive delivery is best-effort;
- explicit response traffic has queue priority;
- push failure never deletes durable mail;
- expired/inactive peers receive no further unsolicited traffic;
- the next valid request makes them active again;
- normal `GET_NEW_MESSAGES` synchronization remains authoritative;
- multiple SSIDs for the same normalized callsign may have distinct APRS activity/address state;
- OpenQSP identity remains the normalized base callsign.

Do not implement persistent subscriptions in M7.

---

## 15. `tools/aprs_sim.py` — deterministic APRS simulator

Implement `tools/aprs_sim.py` or an equivalent clearly named repository tool before real APRS-IS integration is considered complete.

The simulator must reuse production APRS carriage/fragmentation/reassembly logic rather than duplicating it in a toy implementation.

It must support at minimum:

- encode a complete OpenQSP frame into APRS fragment messages;
- decode/reassemble APRS fragments back into the identical OpenQSP frame;
- simulate two peers and the `OPENQSP` service;
- run a complete request/response exchange against real `ServerCore`;
- deterministic seeded fault injection;
- visibility into transmitted packets, ACKs, retries and completed transactions.

### Required fault injection

Support at least:

- drop one selected fragment;
- duplicate one selected fragment;
- reorder fragments;
- delay selected fragments;
- drop one selected APRS ACK;
- duplicate ACK;
- deliver stale ACK;
- resend a complete previously successful request transaction;
- transaction-ID collision with different content.

Fault injection must be deterministic and testable. Prefer an injected clock/event scheduler to real sleeps.

---

## 16. Production code organization

The exact module names may adapt to current repository conventions, but keep responsibilities separable and testable.

A reasonable shape is:

```text
openqsp/transport/aprs/
    carriage.py       # text-safe encoding and fragment syntax
    state.py          # bounded transaction/reassembly/replay state
    reliability.py    # ACK/retry scheduling
    adapter.py        # bridge between APRS packets and ServerCore/session context
    aprsis.py         # APRS-IS connection/line parsing and injection
```

Do not force this exact structure if the repository already has a better transport layout.

Core logic should remain independently testable without an APRS-IS socket.

---

## 17. APRS packet parsing and emission

The APRS-IS adapter must accept only packets relevant to the OpenQSP service.

At minimum validate:

- syntactically usable source address;
- message addressee is `OPENQSP` for inbound OpenQSP carriage;
- text is either a recognized `Q1:` fragment or a relevant `ack<ID>` for pending service-originated traffic;
- malformed or unrelated traffic is ignored/rejected without reaching Core.

For service-originated APRS messages:

- source is `OPENQSP`;
- destination/addressee is the remembered full APRS peer address as appropriate;
- packet construction must be isolated from Core;
- APRS-IS/TCPIP path details remain configurable/deployment concerns.

Do not hardcode private APRS-IS credentials.

---

## 18. APRS-IS connection behaviour

After local simulator conformance passes, implement the real APRS-IS transport path.

### Requirements

- configurable APRS-IS host and port;
- configurable `OPENQSP` passcode supplied externally;
- login line identifies OpenQSP software/version;
- support the `g/OPENQSP` message filter where appropriate;
- parse `# logresp` and require verified service login for production mode;
- reconnect cleanly after disconnect;
- do not lose or corrupt Core durable state when APRS-IS reconnects;
- clear/reconcile ephemeral pending transport state deterministically on connection loss;
- no repository credential files.

The existing manual APRS-IS observations in `design/04-transports.md` are evidence and context, not a replacement for automated adapter tests.

---

## 19. Cross-server APRS-IS verification

The prior experiment observed a successful exchange when both clients used the same Tier-2 server and an inconclusive attempt when independently assigned different servers.

M7 must explicitly verify that the production design does **not** depend on same-server placement.

Before closure, perform and document an APRS-IS test where service and test user are connected through independently selected/possibly different APRS-IS servers.

If cross-server propagation is unreliable in the selected laboratory setup, document the observed limitation and choose a deterministic operational strategy for the server endpoint rather than silently assuming same-server behaviour.

Do not encode a same-Tier-2-server requirement into the OpenQSP application protocol.

---

## 20. RF boundary

M7 must be ready for later RF validation, but automated acceptance must not depend on access to live RF hardware.

The required order is:

1. unit tests;
2. deterministic simulator;
3. local end-to-end adapter tests;
4. APRS-IS Internet-only test;
5. RF/IGate test when equipment and coverage are available.

A missing RF environment must not prevent merging an otherwise complete M7 implementation if simulator and APRS-IS acceptance pass and the remaining RF validation is clearly documented.

No KISS/TNC hardware driver is required unless the current repository explicitly chooses to add it as a separate adapter.

---

## 21. Required local conformance workflows

At minimum create automated workflows proving the following.

### 21.1 Single-frame round trip

```text
canonical OpenQSP request frame
→ APRS encode
→ fragment
→ reassemble
→ decode
→ byte-for-byte identical frame
```

Cover minimum and maximum-size valid OpenQSP frames.

### 21.2 Loss and retry

```text
fragmented request
→ one fragment dropped
→ missing fragment retried
→ ACK received
→ frame completes once
→ Core invoked once
```

### 21.3 Lost ACK

```text
fragment delivered
→ ACK dropped
→ sender retransmits identical fragment with same APRS message ID
→ receiver ACKs again
→ duplicate fragment has no extra Core effect
```

### 21.4 Reordering and duplicates

```text
fragments delivered out of order with duplicates
→ reassembly succeeds
→ exact frame recovered
→ Core invoked once
```

### 21.5 Complete-request replay

```text
request TTT X completes
→ Core returns response
→ same peer resends identical complete TTT X
→ Core is NOT invoked again
→ cached response is replayed
```

### 21.6 Transaction conflict

```text
request TTT X completes
→ same peer sends different bytes under TTT X while cache is valid
→ deterministic transport conflict
→ Core is not invoked for conflicting retry
```

### 21.7 Private-message end to end

```text
EA3AAA APRS request
→ OPENQSP
→ SEND_MESSAGE reaches Core as EA3AAA
→ durable STORED
→ response transported back through APRS simulator
→ recipient synchronizes mailbox
```

### 21.8 Proactive private message

```text
EA3BBB sends valid APRS request and becomes active
→ EA3AAA sends private message to EA3BBB
→ durable store succeeds
→ eligible UNSOLICITED MESSAGE is queued to active APRS address
→ transport failure, if injected, does not remove durable message
→ GET_NEW_MESSAGES remains authoritative
```

---

## 22. Test strategy

Add unit, integration and end-to-end coverage.

Preserve existing tests unless behaviour is intentionally superseded.

### Carriage codec

- [ ] Base64url encode/decode round trip;
- [ ] no `=` emitted;
- [ ] invalid alphabet rejected;
- [ ] malformed fragment header rejected;
- [ ] lower/invalid transaction IDs rejected if profile requires uppercase canonical form;
- [ ] fragment indexes and totals validated;
- [ ] 48-character DATA chunk limit enforced;
- [ ] 16-fragment limit enforced;
- [ ] maximum OpenQSP frame round trip.

### Reassembly

- [ ] in-order fragments;
- [ ] out-of-order fragments;
- [ ] exact duplicate fragment;
- [ ] conflicting duplicate fragment;
- [ ] inconsistent total count;
- [ ] missing fragment timeout;
- [ ] bounded state eviction;
- [ ] malformed completed frame never reaches Core.

### APRS ACK/retry

- [ ] correct ACK correlation;
- [ ] wrong-peer ACK ignored;
- [ ] stale ACK ignored;
- [ ] lost ACK causes retransmission;
- [ ] same APRS message ID reused for retry;
- [ ] retry limit respected;
- [ ] retry state released after completion/failure.

### Replay cache

- [ ] duplicate complete request invokes Core once;
- [ ] cached responses replay in exact original order;
- [ ] same TTT with different content is conflict;
- [ ] cache TTL expiry permits later reuse;
- [ ] bounded cache memory.

### Rate/activity

- [ ] response priority over proactive traffic;
- [ ] bounded outbound queue;
- [ ] rate limiter deterministic with fake clock;
- [ ] valid client request activates peer;
- [ ] ACK alone does not activate peer;
- [ ] activity expires;
- [ ] unsolicited delivery only while active;
- [ ] failed proactive delivery preserves durable mail.

### APRS identity

- [ ] `EA3GNU-10` maps to OpenQSP identity `EA3GNU`;
- [ ] different SSIDs may keep separate APRS routing/activity state;
- [ ] APRS identity is documented/tested as transport-asserted rather than password-authenticated;
- [ ] transport IDs never appear in stored objects.

### APRS-IS

- [ ] login-line generation;
- [ ] verified/unverified `logresp` handling;
- [ ] inbound message parsing;
- [ ] outbound packet generation;
- [ ] reconnect behaviour;
- [ ] credentials supplied externally;
- [ ] unrelated packets ignored safely.

---

## 23. Canonical vectors and examples

Add deterministic M7 carriage examples to repository documentation/tests.

At minimum include:

1. one small OpenQSP frame encoded into one APRS fragment;
2. one maximum/large frame encoded into multiple fragments;
3. the exact reassembled Base64url text;
4. the resulting binary OpenQSP frame in hex;
5. native APRS message ID and matching `ack<ID>` example;
6. a duplicate/replay example showing that APRS IDs and `TTT` never become Core object identifiers.

Canonical examples must be generated/validated against production codec code, not hand-maintained independently without tests.

---

## 24. Documentation updates required

Update documentation so implementation and architecture agree.

At minimum review/update:

- `README.md`;
- `design/04-transports.md`;
- `design/05-roadmap.md`;
- `design/07-client-node-protocol.md` if transport interaction clarification is useful;
- `design/09-protocol-examples.md` or a dedicated APRS profile/example document;
- `tools/README.md`;
- this M7 implementation specification if implementation reveals a necessary clarification.

Document clearly:

- APRS source callsign security limitation;
- Q1 fragment syntax;
- Base64url choice;
- fragment size/count;
- APRS ACK vs OpenQSP `STORED`;
- retry defaults;
- duplicate/replay semantics;
- activity timer semantics;
- APRS-IS configuration and credentials policy;
- how to run the simulator;
- how to perform the APRS-IS conformance test.

---

## 25. Compatibility requirements

M7 must not break the existing Internet/TCP path.

After implementation:

- all existing TCP/client behaviour remains valid;
- M6 callsign+password Internet authentication remains unchanged;
- Core operations remain transport-independent;
- SQLite schema should not require changes solely for APRS transport state;
- mailbox/bulletin sequence semantics remain unchanged;
- protocol canonical vectors remain valid;
- existing 441+ tests remain passing in addition to new M7 tests.

If a persistent schema change appears necessary for APRS retry/reassembly state, treat that as a design smell and re-evaluate: M7 transport state is intended to be ephemeral.

---

## 26. Quality gates

Before declaring M7 complete, run at minimum:

```bash
python -m pytest -q server/tests
ruff check server/src server/tests tools
python -m compileall -q server/src server/tests tools
git diff --check
```

Use the Ruff version pinned by repository CI.

Also run focused M7 tests and the deterministic simulator conformance workflow.

The final GitHub Actions CI must pass.

Do not weaken lint rules, skip existing tests, or add broad ignores to make M7 pass.

---

## 27. Final self-review checklist

Before opening the final PR, inspect the complete diff and answer internally:

### Architecture

- [ ] APRS logic is confined to transport/session-boundary code;
- [ ] Core contains no APRS IDs, fragments or retry logic;
- [ ] no transport IDs are persistent object identity;
- [ ] TCP behaviour remains unchanged.

### Reliability

- [ ] every pending state structure is bounded;
- [ ] every retry has a limit;
- [ ] every incomplete transaction has expiry;
- [ ] duplicate complete requests cannot cause duplicate Core effects while replay state is valid;
- [ ] failed response delivery cannot undo durable Core acceptance.

### Protocol

- [ ] carriage format is canonical and documented;
- [ ] byte-for-byte OpenQSP frame preservation is tested;
- [ ] fragment count/index validation is strict;
- [ ] APRS ACK and `STORED` are visibly distinct.

### Security

- [ ] APRS callsign identity is not described as cryptographically authenticated;
- [ ] no account password is transmitted over APRS;
- [ ] APRS-IS passcode is external to the repository;
- [ ] malformed network input cannot expose stack traces or crash long-lived service loops.

### Testing

- [ ] deterministic fault injection covers loss, duplication, reordering, delay and lost ACK;
- [ ] simulator uses production transport logic;
- [ ] full server tests pass;
- [ ] Ruff passes;
- [ ] compileall passes;
- [ ] GitHub CI passes.

---

## 28. Completion contract

M7 is complete when all of the following are true:

- a canonical APRS carriage profile is implemented and documented;
- complete OpenQSP frames survive encode/fragment/reassembly/decode byte-for-byte;
- native APRS message ACKs drive bounded fragment reliability;
- duplicate fragments are safe;
- duplicate complete transport transactions replay prior Core results rather than invoking Core twice;
- transaction conflicts are detected deterministically;
- all transport/replay state is bounded and ephemeral;
- rate control is present;
- APRS-local activity enables bounded best-effort proactive private-message delivery;
- `tools/aprs_sim.py` or equivalent provides deterministic fault injection;
- a full local request/response workflow passes through the simulator and real Core;
- APRS-IS service login/inbound/outbound behaviour is implemented and tested;
- an Internet-only APRS-IS conformance exchange is documented;
- same-server placement is not silently assumed;
- existing TCP/M6 behaviour remains intact;
- documentation is updated;
- all tests, Ruff, compileall and GitHub CI pass;
- one reviewable M7 PR is opened against `main` and is not auto-merged.

---

## 29. Explicitly out of scope

Do not expand M7 into:

- end-user M8 application work;
- end-to-end encryption;
- cryptographic callsign proof;
- password transport over APRS;
- node federation;
- persistent subscriptions;
- attachments/files;
- message deletion/read receipts;
- generic Packet BBS transport;
- LoRa/VARA transport;
- mandatory RF hardware drivers;
- redesign of the OpenQSP binary application protocol;
- persistence of APRS transaction state in messages/bulletins.

Those require separate milestones or explicit design decisions.
