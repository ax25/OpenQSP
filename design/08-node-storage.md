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

A private-message row contains recipient, mailbox sequence, author, creation and
acceptance timestamps, and body. Its uniqueness invariant is
`UNIQUE(recipient, mailbox_sequence)`. A persistent mailbox high-water row is
kept per recipient.

A bulletin row contains its node-local sequence, creation and acceptance
timestamps, author, title, and body. Its u32 sequence is its primary key and
sole reference. The former global object registry and content hashes existed
only for client-ID idempotency and are removed.

## 5. Scoped synchronization sequences

Message sequences are independent per recipient mailbox. Bulletin sequences
form one node-local stream. Both are unsigned 32-bit and persistent. Allocation
and insertion occur in the same write transaction. Retrieval uses `sequence >
since`, ascending, and validates a message cursor against the authenticated
mailbox's high-water mark. `END.next_since` is the last returned sequence or the
unchanged request cursor for an empty page.

## 6. Accepting a new object

For `SEND_MESSAGE`, validate the request and authenticated author, begin an
immediate write transaction, read the recipient mailbox high-water mark,
allocate the next u32 value, insert the row, update the high-water mark, and
commit. Only after commit may Core return zero-payload `STORED`. Rollback leaves
neither a visible row nor a consumed sequence. Bulletin insertion follows the
same transaction pattern in its node-local stream.

## 7. Durable storage semantics

The node may return `STORED` only after the storage engine confirms that the transaction is committed durably according to the configured durability mode.

At minimum, after `STORED` is returned:

- the complete object must survive a normal process restart;
- indexes and sequence metadata required to retrieve it must be committed;
- the same retry must return `STORED`;
- another object using the same identifier with different content must return `ERROR`.

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
    -> STORED | STORED | ERROR

get_new_messages(recipient, since, max)
    -> ordered messages, next_since, has_more

store_bulletin(authenticated_author, bulletin)
    -> STORED | STORED | ERROR

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
4. An identical retry returns `STORED` without allocating another sequence.
5. The same identifier with different content returns `ERROR`.
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


### Schema version 2 migration

Migration 2 atomically renames the development v1 tables, creates the scoped
schema, and copies content. Messages are resequenced with `ROW_NUMBER()`
partitioned by recipient and ordered by old sequence then old identifier.
Bulletins retain ordering through a single `ROW_NUMBER()`. High-water marks are
initialized from copied rows before obsolete tables are dropped. Authors,
recipients, titles, bodies, and timestamps are preserved; obsolete IDs are not.
