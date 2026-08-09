# 08 - Node Storage

## Purpose

This document defines the minimum persistent storage behaviour required by an OpenQSP node.

It specifies what the node must store, the invariants that storage must preserve, and the transactional behaviour required by the protocol.

It does not mandate a particular database engine, ORM, programming language or physical schema. The first implementation may use SQLite, provided it satisfies every rule in this document.

The canonical object model is defined in `06-object-model.md`. Binary operations and synchronization fields are defined in `03-protocol.md`. Logical client/node behaviour is defined in `07-client-node-protocol.md`.

---

## 1. Scope

OpenQSP version 0.1 persists:

- private messages;
- public bulletins;
- mailbox-local and node-local synchronization sequences.

Version 0.1 does not require persistent storage for:

- devices;
- read state;
- conversations or threads;
- transport delivery attempts;
- APRS activity timers;
- transport retry counters;
- presence;
- groups or channels;
- node federation;
- node-to-node synchronization.

Transport adapters may maintain their own operational state, but that state is outside the core object store defined here.

---

## 2. Storage principles

The node storage layer must provide:

- durable object storage;
- atomic acceptance of new objects;
- stable incremental synchronization;
- persistence across clean and unclean restarts;
- isolation from transport-specific concerns.

An object is considered accepted only after all persistent changes required for that object have committed successfully.

---

## 3. Stored records

A minimal implementation may use two logical record sets:

- `messages`;
- `bulletins`.

This separation is conceptual. A physical implementation may use two tables or another
normalized structure, provided all invariants remain enforceable.

### 3.1 Message record

Each message has:

| Field | Meaning |
|---|---|
| `recipient` | Normalized recipient callsign. |
| `mailbox_sequence` | Monotonic unsigned 32-bit sequence in the recipient mailbox. |
| `author` | Normalized authenticated author callsign. |
| `created_at` | Creation timestamp supplied by the creator/client. |
| `accepted_at` | Node timestamp recorded when the message is durably accepted. |
| `body` | Complete private-message body. |

A message has exactly one author and one recipient in version 0.1.

The persistent identity and required uniqueness constraint are
`UNIQUE(recipient, mailbox_sequence)`. Each mailbox also maintains a persistent high-water
sequence. The node must retrieve messages by this pair efficiently.

### 3.2 Bulletin record

Each bulletin has:

| Field | Meaning |
|---|---|
| `sequence` | Node-local monotonic unsigned 32-bit sequence and bulletin reference. |
| `author` | Normalized author callsign. |
| `created_at` | Creation timestamp supplied by the creator/client. |
| `accepted_at` | Node timestamp recorded when the bulletin is durably accepted. |
| `title` | Mandatory bulletin title. |
| `body` | Complete bulletin body. |

The node must be able to retrieve bulletin headers and complete bulletins by `sequence`
efficiently. There is no separate bulletin identifier.

`accepted_at` is server-managed persistent metadata assigned during durable acceptance. It is
not supplied by the client, is not part of the Core wire representation, and is neither an
application object identifier, a synchronization cursor nor a transport transaction identifier.

---

## 4. Persistent identity and transport state

Messages are identified by `(recipient, mailbox_sequence)` and bulletins by their node-local
`sequence`. Neither is globally unique across object types. Content hashes are not required
solely to make a global identifier idempotent.

Transport retry identifiers, duplicate windows and pending peer transactions belong outside
these records. An unreliable adapter may replay a previously obtained Core result without
turning its transaction identifier into persistent application data.

---

## 5. Synchronization sequences

### 5.1 Independent sequence spaces

The node maintains an independent unsigned 32-bit sequence space for each recipient mailbox,
and one node-local unsigned 32-bit bulletin sequence space.

Each sequence starts at `1`.

`since=0` means that the client has no prior synchronization point and requests objects from the beginning of the retained sequence history.

### 5.2 Assignment

A new message receives the next sequence in its recipient's mailbox. Different mailboxes may
therefore contain identical sequence numbers.

A new bulletin receives the next bulletin sequence.

Sequence assignment and object insertion must occur in the same storage transaction.

### 5.3 Monotonicity

Sequences must:

- increase monotonically;
- never be reused;
- remain stable for the lifetime of the stored object;
- survive node restart;
- remain independent of creator timestamps and transport identifiers.

Sequence gaps are valid. Clients must not assume that every integer value exists.

### 5.4 Retrieval

`GET_NEW_MESSAGES since=S` returns messages for the authenticated recipient with:

```text
mailbox_sequence > S
```

ordered by ascending `mailbox_sequence`.

`GET_NEW_BULLETINS since=S` returns bulletin headers with:

```text
sequence > S
```

ordered by ascending `sequence`.

The operation limit is applied after filtering and ordering.

### 5.5 END and next_since

For a successful multi-item response, `END.next_since` is the highest sequence represented by the completed response.

If at least one item is returned, `next_since` equals the sequence of the final returned item.

If no item is returned, `next_since` equals the request's `since` value.

A client advances its local cursor only after receiving the corresponding valid `END` frame.

### 5.6 Cursor beyond current state

A message `since` value greater than the authenticated mailbox's high-water sequence, or a
bulletin `since` value greater than the node's bulletin high-water sequence, is invalid and
should produce `ERROR / INVALID_CURSOR`.

This rule detects a client cursor belonging to another node, a reset node or corrupted client state instead of silently returning an empty result.

---

## 6. Accepting a new object

Message acceptance must run as one atomic transaction:

1. Validate `created_at`, recipient and body, and obtain the author from authenticated context.
2. Lock or otherwise serialize the recipient mailbox's high-water state.
3. Allocate the next mailbox sequence, assign `accepted_at` and insert the complete message.
4. Advance the mailbox high-water value and commit.
5. Return `STORED` only after that commit.

Bulletin insertion similarly allocates its one node-local sequence, assigns `accepted_at` and
inserts the bulletin in the same transaction.

A failed transaction must not consume a sequence as a protocol-visible accepted object. An implementation may leave internal database sequence gaps after rollback, because gaps are valid, but it must never expose a partially stored object.

---

## 7. Durable storage semantics

The node may return `STORED` only after the storage engine confirms that the transaction is committed durably according to the configured durability mode.

At minimum, after `STORED` is returned:

- the complete object must survive a normal process restart;
- its node-assigned `accepted_at` timestamp must be persisted;
- indexes and sequence metadata required to retrieve it must be committed;
- its assigned sequence and mailbox or bulletin high-water state must remain stable.

The server must not return `STORED` while the object exists only in application memory or an uncommitted transaction.

For the initial SQLite implementation, foreign keys and transactional journaling must be enabled. The selected synchronization mode must not intentionally acknowledge transactions that are expected to disappear after an ordinary operating-system or process failure.

---

## 8. Transaction and concurrency requirements

Storage operations must preserve these invariants under concurrent requests:

- only one message may own a given sequence within a recipient mailbox;
- only one bulletin may own a given node-local bulletin sequence;
- retrieval never observes a partially accepted object.

These rules must be enforced by database constraints and transactions where possible, not only by application-level prechecks.

A recommended constraint set is:

- unique `(recipient, mailbox_sequence)` among messages;
- unique `sequence` among bulletins;
- non-null required application fields;
- persistent high-water state protected by the same transactions as insertion.

---

## 9. Retrieval behaviour

### 9.1 Private messages

A user may retrieve only messages whose normalized `recipient` equals the authenticated OpenQSP user.

The node must not expose another user's mailbox because of an APRS SSID, portable suffix, device identifier or transport address.

Message retrieval returns complete message objects. Version 0.1 has no private-message header retrieval.

### 9.2 Bulletin headers

Bulletin synchronization returns:

- sequence;
- author;
- creation timestamp;
- title.

The bulletin body is not required in the header query.

### 9.3 Complete bulletin

`GET_BULLETIN` retrieves one complete bulletin by `sequence`.

If no bulletin with that sequence exists, the node returns `ERROR / NOT_FOUND`.

---

## 10. Retention and deletion

Version 0.1 does not define user-visible deletion, expiration or automatic object removal.

A conforming minimal node therefore retains accepted messages and bulletins indefinitely unless an administrator performs an explicit maintenance action outside the protocol.

If retention or deletion is introduced later:

- sequence numbers must never be reused;
- the node's highest allocated sequence must not move backwards;
- clients must be able to distinguish an empty result from an invalid or obsolete cursor;
- protocol-visible retention boundaries must be specified before automatic deletion is enabled.

The initial implementation should not add automatic cleanup policies that are invisible to clients.

---

## 11. Restart and recovery

After restart, the node must recover:

- all committed objects;
- their node-assigned `accepted_at` timestamps;
- their assigned sequences;
- each mailbox's and the bulletin stream's high-water state, sufficient to allocate later
  values without reuse.

Temporary transport state does not need to survive restart unless a transport-specific specification requires it later.

Database corruption, failed migrations and unavailable storage are startup failures. The node must not start in a writable mode that could silently create a second sequence history over incomplete data.

---

## 12. Schema evolution

The storage implementation must record a schema version.

Schema changes must be performed through explicit, ordered migrations.

A migration must preserve:

- immutable application content;
- node-managed `accepted_at` metadata;
- mailbox and bulletin sequences;
- uniqueness constraints;
- accepted object visibility.

Destructive automatic schema recreation is not acceptable for a persistent node outside disposable test environments.

---

## 13. Minimum storage interface

The server core should depend on a storage interface equivalent to these logical operations:

```text
store_message(authenticated_author, created_at, recipient, body)
    -> STORED

get_new_messages(recipient, since, max)
    -> ordered messages, next_since, has_more

store_bulletin(authenticated_author, bulletin)
    -> STORED

get_new_bulletin_headers(since, max)
    -> ordered headers, next_since, has_more

get_bulletin(sequence)
    -> bulletin | NOT_FOUND

get_sequence_state(recipient)
    -> mailbox high-water sequence, bulletin high-water sequence
```

`store_bulletin` is included in the storage boundary even though version 0.1 has not yet assigned a client protocol operation for bulletin publication. It may initially be used by an administrative tool or test fixture.

The storage interface must not accept transport addresses, sockets, APRS paths or connection objects.

---

## 14. Minimum acceptance tests

A storage implementation is ready for use by the minimal server when automated tests demonstrate that:

1. A new message is stored with sequence `1` in an empty recipient mailbox.
2. A second message in that mailbox receives a greater sequence.
3. Different mailboxes can each contain sequence `1` and remain isolated.
4. Bulletin sequences are independent from every mailbox sequence.
5. A recipient retrieves only its own messages.
6. Retrieval is ordered by sequence and respects `since` and `max`.
7. `next_since` and `has_more` are correct for empty, partial and complete pages.
8. A cursor above the relevant mailbox or bulletin sequence returns `INVALID_CURSOR`.
9. A bulletin header excludes the body and a complete sequence lookup includes it.
10. An unknown bulletin sequence returns `NOT_FOUND`.
11. Committed objects, per-mailbox high-water values and bulletin allocation survive restart.
12. A failed transaction exposes no partial object or protocol-visible accepted sequence.
13. Concurrent insertions preserve uniqueness and monotonic allocation in each sequence space.

---

## 15. Deferred storage concerns

The following storage concerns are intentionally deferred:

- per-device synchronization state;
- read and unread flags;
- outbound transport queues;
- delivery receipts;
- message deletion;
- retention windows;
- attachments;
- full-text search;
- bulletin channels;
- moderation history;
- federation metadata;
- replication and high availability.

They must not be added to the minimal schema unless another approved design document first defines their protocol and domain semantics.

## Schema version 3: accounts

Migration 3 adds the independent `accounts(callsign, password_hash, created_at)` table without modifying messages, bulletins, or their sequence allocators. Callsigns are canonical primary keys. Passwords use per-account random 128-bit salts and PBKDF2-HMAC-SHA256 with 600,000 iterations and a 256-bit derived key. Verification uses constant-time digest comparison and a dummy derivation for unknown accounts. Provisioning is an administrative CLI action; there is no network self-registration.
