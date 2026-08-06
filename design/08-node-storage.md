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
- node-local synchronization sequences;
- the minimum metadata needed for deduplication and conflict detection.

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
- idempotent duplicate handling;
- deterministic conflict detection;
- stable incremental synchronization;
- persistence across clean and unclean restarts;
- isolation from transport-specific concerns.

An object is considered accepted only after all persistent changes required for that object have committed successfully.

---

## 3. Stored records

A minimal implementation may use three logical record sets:

- `objects`;
- `messages`;
- `bulletins`.

This separation is conceptual. A physical implementation may use two tables, three tables or another normalized structure, provided all invariants remain enforceable.

### 3.1 Common object record

Every stored object has:

| Field | Meaning |
|---|---|
| `object_id` | Globally unique unsigned 64-bit object identifier. |
| `object_type` | `MESSAGE` or `BULLETIN`. |
| `author` | Normalized OpenQSP callsign. |
| `created_at` | Object creation timestamp supplied by its creator. |
| `accepted_at` | Node timestamp recorded when the object is durably accepted. |
| `content_hash` | Deterministic hash of the immutable canonical object content. |

`object_id` is unique across all object types within one node. A message and a bulletin cannot share the same identifier.

`accepted_at` is node metadata. It is not part of the immutable content used to determine whether a retry is identical.

### 3.2 Message record

Each message additionally has:

| Field | Meaning |
|---|---|
| `message_sequence` | Node-local monotonic synchronization sequence. |
| `recipient` | Normalized recipient callsign. |
| `body` | Complete private-message body. |

A message has exactly one author and one recipient in version 0.1.

The node must be able to retrieve messages by recipient and `message_sequence` efficiently.

### 3.3 Bulletin record

Each bulletin additionally has:

| Field | Meaning |
|---|---|
| `bulletin_sequence` | Node-local monotonic synchronization sequence. |
| `title` | Mandatory bulletin title. |
| `body` | Complete bulletin body. |

The node must be able to retrieve bulletin headers and complete bulletins by `bulletin_sequence` and `object_id` efficiently.

---

## 4. Object identity and canonical content

### 4.1 Global object identifier

`object_id` identifies immutable application content independently of transport and node-local synchronization order.

Retries of one object must reuse the same `object_id` and identical canonical content.

### 4.2 Canonical message content

For duplicate and conflict comparison, the canonical content of a message consists of:

- object type `MESSAGE`;
- `object_id`;
- normalized `author`;
- normalized `recipient`;
- `created_at`;
- exact body bytes.

### 4.3 Canonical bulletin content

For duplicate and conflict comparison, the canonical content of a bulletin consists of:

- object type `BULLETIN`;
- `object_id`;
- normalized `author`;
- `created_at`;
- exact title bytes;
- exact body bytes.

Node metadata such as sequence numbers and `accepted_at` must not be included in canonical object content.

### 4.4 Content hash

The implementation may use a cryptographic hash to accelerate comparison, but hash equality alone must not silently permit conflicting content if the implementation can compare the stored canonical fields directly.

The hash algorithm is an implementation detail in version 0.1 and is not exchanged in the protocol.

---

## 5. Node-local synchronization sequences

### 5.1 Independent sequence spaces

The node maintains two independent unsigned 64-bit sequence spaces:

- `message_sequence`;
- `bulletin_sequence`.

Each sequence starts at `1`.

`since=0` means that the client has no prior synchronization point and requests objects from the beginning of the retained sequence history.

### 5.2 Assignment

A new message receives the next message sequence.

A new bulletin receives the next bulletin sequence.

Sequence assignment and object insertion must occur in the same storage transaction.

### 5.3 Monotonicity

Sequences must:

- increase monotonically;
- never be reused;
- remain stable for the lifetime of the stored object;
- survive node restart;
- remain independent of creator timestamps and object identifiers.

Sequence gaps are valid. Clients must not assume that every integer value exists.

### 5.4 Retrieval

`GET_NEW_MESSAGES since=S` returns messages for the authenticated recipient with:

```text
message_sequence > S
```

ordered by ascending `message_sequence`.

`GET_NEW_BULLETINS since=S` returns bulletin headers with:

```text
bulletin_sequence > S
```

ordered by ascending `bulletin_sequence`.

The operation limit is applied after filtering and ordering.

### 5.5 END and next_since

For a successful multi-item response, `END.next_since` is the highest sequence represented by the completed response.

If at least one item is returned, `next_since` equals the sequence of the final returned item.

If no item is returned, `next_since` equals the request's `since` value.

A client advances its local cursor only after receiving the corresponding valid `END` frame.

### 5.6 Cursor beyond current state

A `since` value greater than the highest sequence currently known by the node is invalid and should produce `ERROR / INVALID_CURSOR`.

This rule detects a client cursor belonging to another node, a reset node or corrupted client state instead of silently returning an empty result.

---

## 6. Accepting a new object

Object acceptance must run as one atomic transaction.

For a submitted object, the node performs these logical steps:

1. Validate the complete object and authenticated author.
2. Look up `object_id` across all stored object types.
3. If the identifier does not exist:
   - allocate the next sequence for its type;
   - store the common and type-specific fields;
   - commit the transaction;
   - return `ACK / STORED`.
4. If the identifier exists with identical canonical content:
   - make no persistent change;
   - return `ACK / ALREADY_STORED`.
5. If the identifier exists with different type or content:
   - make no persistent change;
   - return `ACK / CONFLICT`.

A failed transaction must not consume a sequence as a protocol-visible accepted object. An implementation may leave internal database sequence gaps after rollback, because gaps are valid, but it must never expose a partially stored object.

---

## 7. Durable storage semantics

The node may return `ACK / STORED` only after the storage engine confirms that the transaction is committed durably according to the configured durability mode.

At minimum, after `STORED` is returned:

- the complete object must survive a normal process restart;
- indexes and sequence metadata required to retrieve it must be committed;
- the same retry must return `ALREADY_STORED`;
- another object using the same identifier with different content must return `CONFLICT`.

The server must not return `STORED` while the object exists only in application memory or an uncommitted transaction.

For the initial SQLite implementation, foreign keys and transactional journaling must be enabled. The selected synchronization mode must not intentionally acknowledge transactions that are expected to disappear after an ordinary operating-system or process failure.

---

## 8. Transaction and concurrency requirements

Storage operations must preserve these invariants under concurrent requests:

- only one object may own an `object_id`;
- only one accepted object may own a given sequence within its type;
- duplicate submissions cannot create duplicate rows;
- conflicting submissions cannot overwrite accepted content;
- retrieval never observes a partially accepted object.

These rules must be enforced by database constraints and transactions where possible, not only by application-level prechecks.

A recommended constraint set is:

- unique `object_id` across all objects;
- unique `message_sequence` among messages;
- unique `bulletin_sequence` among bulletins;
- non-null canonical fields;
- object-type consistency between common and type-specific records.

---

## 9. Retrieval behaviour

### 9.1 Private messages

A user may retrieve only messages whose normalized `recipient` equals the authenticated OpenQSP user.

The node must not expose another user's mailbox because of an APRS SSID, portable suffix, device identifier or transport address.

Message retrieval returns complete message objects. Version 0.1 has no private-message header retrieval.

### 9.2 Bulletin headers

Bulletin synchronization returns:

- object identifier;
- bulletin sequence;
- author;
- creation timestamp;
- title.

The bulletin body is not required in the header query.

### 9.3 Complete bulletin

`GET_BULLETIN` retrieves one complete bulletin by `object_id`.

If no bulletin with that identifier exists, the node returns `ERROR / NOT_FOUND`.

If the identifier belongs to another object type, it is also treated as not being a bulletin and returns `NOT_FOUND` to this operation.

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
- their stable object identifiers;
- their assigned sequences;
- enough sequence state to allocate later values without reuse;
- deduplication and conflict behaviour.

Temporary transport state does not need to survive restart unless a transport-specific specification requires it later.

Database corruption, failed migrations and unavailable storage are startup failures. The node must not start in a writable mode that could silently create a second sequence history over incomplete data.

---

## 12. Schema evolution

The storage implementation must record a schema version.

Schema changes must be performed through explicit, ordered migrations.

A migration must preserve:

- object identifiers;
- immutable canonical content;
- message and bulletin sequences;
- uniqueness constraints;
- accepted object visibility.

Destructive automatic schema recreation is not acceptable for a persistent node outside disposable test environments.

---

## 13. Minimum storage interface

The server core should depend on a storage interface equivalent to these logical operations:

```text
store_message(authenticated_author, message)
    -> STORED | ALREADY_STORED | CONFLICT

get_new_messages(recipient, since, max)
    -> ordered messages, next_since, has_more

store_bulletin(authenticated_author, bulletin)
    -> STORED | ALREADY_STORED | CONFLICT

get_new_bulletin_headers(since, max)
    -> ordered headers, next_since, has_more

get_bulletin(object_id)
    -> bulletin | NOT_FOUND

get_sequence_state()
    -> highest message sequence, highest bulletin sequence
```

`store_bulletin` is included in the storage boundary even though version 0.1 has not yet assigned a client protocol operation for bulletin publication. It may initially be used by an administrative tool or test fixture.

The storage interface must not accept transport addresses, sockets, APRS paths or connection objects.

---

## 14. Minimum acceptance tests

A storage implementation is ready for use by the minimal server when automated tests demonstrate that:

1. A new message is stored with sequence `1` in an empty database.
2. A second message receives a greater message sequence.
3. Bulletin sequences are independent from message sequences.
4. An identical retry returns `ALREADY_STORED` without allocating another sequence.
5. The same identifier with different content returns `CONFLICT`.
6. The same identifier cannot be used by both a message and a bulletin.
7. A recipient retrieves only its own messages.
8. Retrieval is ordered by sequence and respects `since` and `max`.
9. `next_since` and `has_more` are correct for empty, partial and complete pages.
10. A cursor above the current sequence returns `INVALID_CURSOR`.
11. A bulletin header excludes the body and a complete lookup includes it.
12. An unknown bulletin identifier returns `NOT_FOUND`.
13. Committed objects and sequence allocation survive restart.
14. A failed transaction exposes no partial object.
15. Concurrent duplicate submissions create only one stored object.

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
