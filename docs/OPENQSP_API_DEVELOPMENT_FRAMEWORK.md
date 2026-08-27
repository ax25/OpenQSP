# OpenQSP Internet API v1 — Development Framework

**Status:** Development baseline  
**Audience:** OpenQSP maintainers and coding agents  
**Purpose:** Define the architecture, scope, contract, implementation constraints, validation requirements, and completion criteria for the first production-oriented Internet API used by official OpenQSP clients, especially the Flutter application.

---

## 1. Purpose

OpenQSP must support official clients through two transport modes: Internet and APRS. This document defines the development framework for **Internet mode**.

The Internet API is an adapter to OpenQSP, not a second implementation of OpenQSP. HTTP, WebSocket, TCP and APRS should reuse the same domain rules and services whenever possible.

```text
                         OpenQSP clients
                               │
                 ┌─────────────┼─────────────┐
                 │             │             │
               TCP          HTTP/WS        APRS
                 │             │             │
                 └─────────────┼─────────────┘
                               │
                       OpenQSP services
                               │
                         repositories
                               │
                            database
```

---

## 2. Primary objective

Implement a versioned API under:

```text
/api/v1
```

that allows an official OpenQSP client to:

- authenticate using callsign and password;
- identify the authenticated user;
- list private messages;
- retrieve a conversation with another callsign;
- retrieve an individual message;
- send a private message;
- safely retry sends without duplicates;
- synchronize incrementally after periods offline;
- receive new-message events in real time through WebSocket;
- recover after WebSocket/network interruption.

The minimum complete client flow is:

```text
login → inbox → conversation → history → send → realtime receive → disconnect → reconnect + sync
```

---

## 3. Source of truth and implementation philosophy

Before changing code, inspect the repository and identify the current implementation of:

- account storage and authentication;
- callsign normalization/validation;
- private-message creation/retrieval;
- message identifiers and sequencing;
- repositories and persistence;
- ACK/state semantics;
- protocol validation;
- TCP server commands;
- APRS integration points;
- configuration;
- tests and CI.

### Required principle

Reuse existing domain code instead of recreating it in HTTP.

Avoid separate business logic such as:

```text
send_message_tcp()
send_message_http()
send_message_aprs()
```

Prefer one reusable domain operation such as:

```text
MessageService.send(...)
```

If transport and domain logic are currently mixed, perform only the minimum safe refactor needed to expose reusable services. Do not redesign unrelated parts of OpenQSP.

---

## 4. Scope

### Included in API v1

- HTTP JSON API;
- bearer-token authentication;
- login;
- authenticated-user endpoint;
- private-message creation;
- private-message listing;
- conversation filtering;
- individual-message retrieval;
- cursor pagination;
- incremental synchronization;
- idempotent message submission;
- WebSocket new-message events;
- consistent JSON errors;
- OpenAPI documentation;
- configuration needed to run the API;
- automated tests;
- operational/developer documentation.

### Explicitly out of scope

Unless required by the existing architecture, do not implement:

- public registration;
- password recovery;
- OAuth/social login;
- complex refresh-token infrastructure;
- mobile push notifications;
- Flutter APRS transport;
- attachments;
- groups/channels;
- presence or typing indicators;
- editing/deleting messages;
- read receipts if not already domain concepts;
- large database redesigns;
- admin dashboards.

---

## 5. Technology selection

Reuse an existing HTTP framework if the repository already has an appropriate one.

If not, **FastAPI is the preferred default** because it provides async support, WebSockets, typed validation, OpenAPI and interactive documentation.

Follow the project’s existing dependency-management conventions and avoid unnecessary dependencies.

---

## 6. General API conventions

Base path:

```text
/api/v1
```

Requests/responses use JSON. Timestamps are UTC RFC3339/ISO8601, e.g.:

```text
2026-08-27T20:00:00Z
```

Callsign handling must reuse the current domain normalization and validation rules.

Message identifiers exposed through HTTP must preserve the semantics of the existing OpenQSP message model. Do not invent unrelated HTTP-only IDs unless needed to make existing contextual IDs unambiguous; if so, use an opaque API representation and document/test the mapping.

---

## 7. Authentication

### Login

```http
POST /api/v1/auth/login
```

Request:

```json
{
  "callsign": "EA3GNU",
  "password": "example-password"
}
```

Response:

```json
{
  "access_token": "<token>",
  "token_type": "bearer",
  "user": {
    "callsign": "EA3GNU"
  }
}
```

Protected endpoints use:

```http
Authorization: Bearer <token>
```

Requirements:

- authenticate against the current OpenQSP account system;
- never store/log plaintext passwords;
- enforce token expiry;
- keep secrets configurable, never hardcoded;
- reject malformed/expired/invalid tokens;
- derive user identity from the token, not request JSON;
- do not reveal whether an account exists on login failure.

Recommended auth error code:

```text
invalid_credentials
```

A signed access token or opaque server-side token are both acceptable; choose whichever fits the repository best. Do not add complex refresh-token machinery in v1.

---

## 8. Authenticated user

```http
GET /api/v1/me
```

Response:

```json
{
  "callsign": "EA3GNU"
}
```

Used for session restoration, identity confirmation and authenticated connectivity checks.

---

## 9. Canonical private-message representation

Minimum shape:

```json
{
  "id": "42",
  "from": "EA3GNU",
  "to": "EA3ABC",
  "body": "Hello from OpenQSP.",
  "created_at": "2026-08-27T20:00:00Z"
}
```

Only expose additional fields if they already have meaningful domain semantics. Internet/APRS are transports and should not create different logical-message models.

---

## 10. Send private message

```http
POST /api/v1/messages
```

Request:

```json
{
  "to": "EA3ABC",
  "body": "Hello from OpenQSP."
}
```

The sender is always derived from authentication. A client-provided `from` must never override it.

Success:

```http
201 Created
```

```json
{
  "message": {
    "id": "42",
    "from": "EA3GNU",
    "to": "EA3ABC",
    "body": "Hello from OpenQSP.",
    "created_at": "2026-08-27T20:00:00Z"
  }
}
```

Use the same domain/service logic as other transports and preserve current validation, message limits, persistence, ID allocation and ACK/state semantics.

---

## 11. Idempotent send

Support:

```http
Idempotency-Key: <client-generated-key>
```

on `POST /api/v1/messages`.

Requirements:

- scoped at least by authenticated user + operation;
- same key and same logical request returns the original result without creating another message;
- concurrent retries must not create duplicates;
- persistence/transaction handling must be coherent;
- if the same key is reused with a materially different payload, return a deterministic conflict/validation response;
- do not use the idempotency key as the domain message ID unless the current architecture clearly supports that model.

Add tests for sequential and concurrent retries.

---

## 12. List messages

```http
GET /api/v1/messages
```

Returns messages sent or received by the authenticated user.

Example:

```json
{
  "messages": [
    {
      "id": "41",
      "from": "EA3ABC",
      "to": "EA3GNU",
      "body": "Received.",
      "created_at": "2026-08-27T19:58:00Z"
    }
  ],
  "next_cursor": null
}
```

Pagination parameters:

```text
limit   default 50, maximum 200
cursor  opaque continuation cursor
```

Prefer cursor pagination over offset. Ordering must be deterministic and stable even when timestamps are equal.

---

## 13. Conversation filtering

Support:

```http
GET /api/v1/messages?with=EA3ABC
```

Return only messages exchanged between the authenticated user and the requested callsign, including both directions. Pagination must continue to work.

---

## 14. Individual message

```http
GET /api/v1/messages/{id}
```

A user may retrieve only messages for which they are sender or recipient.

Return `404 Not Found` both when the message does not exist and when it belongs only to third parties, avoiding information disclosure.

---

## 15. Incremental synchronization

Implement:

```http
GET /api/v1/sync
GET /api/v1/sync?cursor=<opaque-cursor>
```

First call returns the current synchronization dataset plus a cursor. Later calls return only changes after that cursor.

Example:

```json
{
  "messages": [
    {
      "id": "43",
      "from": "EA3ABC",
      "to": "EA3GNU",
      "body": "New message",
      "created_at": "2026-08-27T20:02:00Z"
    }
  ],
  "cursor": "<opaque-cursor>"
}
```

The cursor must:

- be opaque to clients;
- not depend on the client clock;
- not require clients to understand database IDs;
- provide deterministic ordering;
- avoid missed changes between successive calls;
- isolate one user’s data from another’s.

A monotonic server-side sequence is acceptable if it fits the existing persistence model, but first inspect current message IDs and storage.

Tests must cover zero, one and multiple changes; repeated calls; equal timestamps; invalid cursors; and user isolation.

---

## 16. WebSocket

Implement:

```text
/api/v1/ws
```

The connection must authenticate the user using a browser/Flutter-compatible mechanism.

Minimum server event:

```json
{
  "type": "message.created",
  "data": {
    "id": "43",
    "from": "EA3ABC",
    "to": "EA3GNU",
    "body": "New message",
    "created_at": "2026-08-27T20:02:00Z"
  }
}
```

Requirements:

- deliver only to relevant authenticated users;
- clean up disconnected sockets;
- support multiple connections for one user if practical;
- never make WebSocket the sole source of truth;
- emit only after successful persistence/commit.

---

## 17. Reconnection model

The intended client behavior is:

```text
HTTP sync = source of truth
WebSocket = low-latency notification
```

After disconnect/reconnect, the client must run `/sync` with its last stored cursor to recover any events missed while offline. WebSocket does not need durable replay if sync provides correct recovery.

---

## 18. Error model

Use one JSON envelope:

```json
{
  "error": {
    "code": "invalid_credentials",
    "message": "Invalid callsign or password."
  }
}
```

Validation may add structured details:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Invalid request.",
    "details": {
      "to": "Invalid callsign."
    }
  }
}
```

Initial error codes should include as applicable:

```text
invalid_request
validation_error
invalid_credentials
invalid_token
forbidden
not_found
message_too_long
conflict
rate_limited
internal_error
```

Do not leak stack traces, SQL errors, secrets or internal paths in production responses.

---

## 19. HTTP status conventions

Use standard semantics:

| Status | Meaning |
|---|---|
| 200 | successful request |
| 201 | resource/message created |
| 400 | malformed/invalid request |
| 401 | authentication required/invalid |
| 403 | authenticated but forbidden |
| 404 | not found / hidden resource |
| 409 | idempotency or state conflict |
| 422 | validation error when framework conventions make it appropriate |
| 429 | rate limited |
| 500 | unexpected internal error |

Keep behavior consistent across routes.

---

## 20. Message-size semantics

Do not blindly copy an APRS frame limit into HTTP. The API should validate the logical OpenQSP message according to the current domain rules.

If OpenQSP itself defines a logical maximum, all transports must enforce it. If only APRS frames impose a transport limit, future APRS code should handle fragmentation/encoding without changing the Internet API’s logical message model.

---

## 21. CORS

The Flutter web client will eventually need browser access.

CORS must therefore be configurable. Do not ship an unsafe unrestricted production configuration by accident. Local development may allow explicitly configured localhost origins.

---

## 22. Configuration

New settings must integrate with the project’s current configuration system.

Likely settings include, depending on implementation:

- API bind host;
- API port;
- token/session secret;
- token lifetime;
- allowed CORS origins.

Sensitive values must be supplied through configuration/environment and must not be committed as real secrets.

---

## 23. OpenAPI and developer docs

Expose generated OpenAPI documentation when supported by the selected framework.

For FastAPI, the normal local development expectation is equivalent to:

```text
/docs
/openapi.json
```

Document the actual URLs and commands in repository docs.

OpenAPI should accurately describe authentication, requests, responses and error conditions where practical.

---

## 24. Security baseline

At minimum:

- authenticate every protected HTTP route;
- authenticate WebSocket connections;
- derive sender identity from auth state;
- restrict private-message reads to participants;
- use expiring tokens/sessions;
- keep credentials/secrets out of logs;
- avoid account-existence disclosure;
- avoid exposing third-party message existence;
- use parameterized repository/database operations;
- validate inputs through domain rules;
- make production secret configuration explicit.

Do not implement custom cryptography when established libraries solve the problem.

---

## 25. Testing requirements

Add API-specific automated tests and preserve all existing tests.

Cover at minimum:

### Authentication
- successful login;
- wrong password;
- unknown account indistinguishable from wrong password;
- missing token;
- invalid token;
- expired token;
- `/me` identity.

### Messages
- valid send;
- sender cannot be spoofed;
- invalid recipient;
- invalid/too-long body according to domain rules;
- sender sees sent message;
- recipient sees received message;
- third party cannot retrieve private message;
- conversation filter works both directions;
- deterministic pagination.

### Idempotency
- same key does not duplicate;
- same key returns stable original result;
- same key with conflicting payload behaves deterministically;
- keys are isolated between users;
- concurrency does not create duplicates.

### Sync
- initial sync;
- no-change sync;
- one/multiple changes;
- successive cursor advancement;
- equal timestamps;
- invalid cursor;
- user isolation;
- no duplicate after cursor advancement.

### WebSocket
- authenticated connect;
- rejected unauthenticated/invalid connection;
- recipient receives `message.created`;
- unrelated users do not receive it;
- cleanup after disconnect;
- reconnect + `/sync` recovers missed message.

### Regression
Run the complete existing OpenQSP suite and ensure TCP/APRS behavior is not broken by API changes.

---

## 26. Quality gates

Inspect CI and run the same relevant checks locally where possible:

- tests;
- formatter;
- linter;
- type checker;
- packaging/build validation.

Do not change project-wide lint or formatting policy merely to make the new code pass. Keep unrelated diffs minimal.

---

## 27. Documentation deliverables

Update repository documentation so another developer can use the API without reading implementation code.

Document at minimum:

1. what the Internet API is;
2. dependency installation;
3. required configuration;
4. local startup command;
5. how to use existing test accounts;
6. Swagger/OpenAPI location;
7. login example;
8. message-send example;
9. synchronization workflow;
10. WebSocket reconnect workflow.

Do not manually duplicate a large generated OpenAPI schema into Markdown.

---

## 28. Recommended internal implementation order

The coding agent should proceed autonomously without requesting approval between phases.

### Phase A — Repository analysis
Map auth, domain, persistence, server startup, tests and CI.

### Phase B — Domain/service reuse
Expose/refactor only the reusable auth/message operations required while preserving TCP behavior.

### Phase C — HTTP foundation
Application/router setup, configuration, common errors, authentication, OpenAPI and CORS.

### Phase D — Core endpoints
Implement login, `/me`, message create/list/get, conversation filtering and pagination.

### Phase E — Idempotency
Implement persistence/concurrency semantics and tests.

### Phase F — Sync
Implement opaque cursor synchronization and edge cases.

### Phase G — WebSocket
Implement authenticated realtime `message.created` routing and cleanup.

### Phase H — Integration tests
Run realistic multi-user scenarios end-to-end.

### Phase I — Documentation and final validation
Update docs, run full suite/quality checks, inspect diff and report final state.

Do not stop after scaffolding or leave TODOs for required functionality.

---

## 29. Acceptance scenario

Before the task is considered complete, verify this scenario against a test database using real API calls.

Accounts:

```text
EA3GNU
EA3ABC
```

Scenario:

1. EA3GNU logs in successfully.
2. EA3ABC logs in successfully.
3. Both `/me` endpoints return correct identities.
4. Both open authenticated WebSockets.
5. EA3GNU sends `Radio test` to EA3ABC with an Idempotency-Key.
6. API returns `201` with a persisted canonical message.
7. Repeating the same POST/key creates no duplicate.
8. EA3ABC receives `message.created` via WebSocket.
9. EA3ABC lists messages and sees the received message.
10. EA3GNU lists messages and sees the sent message.
11. EA3ABC retrieves the conversation using `?with=EA3GNU`.
12. A third test user, if available, cannot retrieve the private message.
13. EA3ABC stores a sync cursor.
14. Its WebSocket disconnects.
15. EA3GNU sends another message.
16. EA3ABC reconnects later.
17. `/sync?cursor=...` returns the missed message.
18. Advancing the cursor and syncing again returns no duplicate change.
19. Existing non-API OpenQSP tests still pass.

This is the minimum viable Internet transport required by the Flutter application.

---

## 30. Compatibility with future Flutter client

The API must allow Flutter to hide transport details behind an abstraction conceptually similar to:

```dart
abstract class OpenQspTransport {
  Future<void> connect();
  Future<void> disconnect();
  Future<void> sendMessage(...);
  Stream<OpenQspEvent> get events;
}
```

Internet mode should use:

```text
HTTP      → authentication, history, sending, synchronization
WebSocket → low-latency event notification
```

A future APRS implementation should be able to satisfy the same higher-level app operations without the UI understanding APRS frames.

Do not add Flutter code to the server repository as part of this task.

---

## 31. Database changes

Prefer existing tables/repositories.

Schema changes are acceptable only when genuinely needed for correctness, e.g.:

- idempotency state;
- deterministic synchronization sequencing.

If needed:

- use the project migration mechanism if present;
- preserve existing data;
- keep changes minimal;
- test initialization/migration;
- explain the reason in the final report.

Do not introduce a monotonic sequence blindly before understanding current IDs/storage.

---

## 32. Concurrency and transactions

Message creation, idempotency and sync sequencing must have coherent transaction semantics.

Avoid cases where:

- a message commits but idempotency state does not;
- two concurrent retries create two messages;
- sync advances past an uncommitted message;
- WebSocket emits an event for a transaction that later rolls back.

Prefer realtime event emission after successful commit.

---

## 33. Logging

Follow existing logging conventions.

Useful operational events may include API startup/shutdown, WebSocket connect/disconnect and unexpected exceptions.

Never log plaintext passwords, bearer tokens, token secrets or other credentials. Avoid normal production logging of full private-message bodies unless that is already explicit project policy.

---

## 34. Versioning rule

All routes introduced here belong to:

```text
/api/v1
```

Once official clients depend on v1, do not casually break request/response semantics. Add backward-compatible fields where possible; breaking changes require deliberate versioning/migration planning.

---

## 35. Completion criteria

The implementation is complete only when all applicable items are true:

- [ ] repository architecture inspected before implementation;
- [ ] existing domain logic reused;
- [ ] existing TCP behavior remains functional;
- [ ] `/api/v1/auth/login` implemented;
- [ ] `/api/v1/me` implemented;
- [ ] `POST /api/v1/messages` implemented;
- [ ] `GET /api/v1/messages` implemented;
- [ ] `GET /api/v1/messages?with=...` implemented;
- [ ] `GET /api/v1/messages/{id}` implemented;
- [ ] cursor pagination implemented;
- [ ] `Idempotency-Key` implemented;
- [ ] `/api/v1/sync` implemented;
- [ ] opaque synchronization cursor implemented;
- [ ] `/api/v1/ws` implemented;
- [ ] `message.created` goes only to relevant users;
- [ ] reconnect + sync recovery tested;
- [ ] common error model implemented;
- [ ] OpenAPI documentation available;
- [ ] CORS configurable;
- [ ] sensitive settings configurable/not hardcoded;
- [ ] API-specific tests pass;
- [ ] complete existing test suite passes;
- [ ] relevant lint/type/format/build checks pass;
- [ ] local startup procedure documented;
- [ ] acceptance scenario verified;
- [ ] no unrelated large refactor introduced.

---

## 36. Final coding-agent report

After finishing, report concisely:

### Architecture
- framework/approach selected;
- where the API lives;
- how existing domain logic is reused;
- schema changes, if any.

### Implemented endpoints
List all routes and authentication requirements.

### Configuration
List new environment/configuration variables.

### Tests
Report API-specific results, full repository tests and lint/type/format/build checks.

### How to run
Provide exact commands for dependency installation, local API startup, opening API docs and executing tests.

### Acceptance test
State whether the two-user send/retry/WebSocket/disconnect/sync scenario passed.

### Remaining limitations
Mention only genuine known limitations or deliberately deferred features.

Do not present planned work as completed work.

---

## 37. Development autonomy rule

This framework is intended to support autonomous implementation by a coding agent.

The agent must not stop to request approval between normal implementation phases.

When a detail is unspecified:

1. inspect repository conventions;
2. choose the smallest architecture-compatible solution;
3. implement it;
4. cover the decision with tests where appropriate;
5. document meaningful choices in the final report.

Only stop when a real blocker cannot be solved from the repository/local environment, such as unavailable required credentials or an unavoidable external service dependency.

A failed optional external-network operation is not sufficient reason to abandon implementation if development and tests can continue locally.

The desired outcome is a finished, tested, documented API—not a proposal or scaffold.
