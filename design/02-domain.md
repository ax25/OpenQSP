# OpenQSP Domain Overview

## Purpose

This document describes the domain boundaries and relationships of OpenQSP at a high level.

The canonical fields and rules for each object are defined in `06-object-model.md`. Logical client/node operations are defined in `07-client-node-protocol.md`.

This document does not define database tables, APIs, binary encoding, transport framing or implementation details.

---

## 1. Domain scope

OpenQSP version 0.1 implements the minimum domain required for a persistent amateur-radio BBS.

Its domain concepts are:

- `User`;
- `Node`;
- `Message`;
- `Bulletin`.

```text
                         +-------------+
                         |    User     |
                         +------+------+ 
                                |
                    authors     |     receives
                                |
                  +-------------+-------------+
                  |                           |
                  v                           v
           +-------------+             +-------------+
           |   Message   |             |  Bulletin   |
           +------+------+             +-------------+
                  |
             stored by
                  |
                  v
           +-------------+
           |    Node     |
           +-------------+
```

The initial domain intentionally does not include conversations, threads, devices, delivery-attempt objects, presence, groups or federation peers.

---

## 2. User

A `User` is one OpenQSP identity represented by a normalized amateur-radio callsign.

The user exists independently of the transport used to reach a node. APRS SSIDs and operating suffixes such as `/P` or `/M` do not create separate users or mailboxes.

A user may:

- send private messages;
- receive private messages;
- publish bulletins when permitted;
- access the same mailbox through different clients or transports.

Authentication and transport-address resolution are outside the domain model.

---

## 3. Node

A `Node` is the BBS endpoint with which clients communicate.

A node:

- accepts and validates objects;
- stores messages and bulletins durably;
- makes stored objects available to users;
- answers synchronization and retrieval requests;
- coordinates transport adapters.

A node is not a user and does not gain a user mailbox merely because it operates under an amateur-radio callsign.

Federation and synchronization between nodes are outside the scope of version 0.1.

---

## 4. Message

A `Message` is one persistent private text object sent from one user to another.

A message:

- has exactly one author and one recipient in version 0.1;
- has no title, subject, conversation identifier or thread identifier;
- is independent of the transport used to submit or retrieve it;
- is immutable after creation;
- is downloaded in full.

The node assigns a message sequence in its recipient mailbox. A correction is represented by a
new message; transport retries do not define persistent identity.

Transport attempts, link acknowledgements, retry counters and temporary routing state are operational concerns and are not separate domain entities in version 0.1.

---

## 5. Bulletin

A `Bulletin` is one persistent public news object.

A bulletin:

- has one author;
- has a mandatory title;
- has a body;
- has no private recipient;
- is immutable after creation.

Clients normally discover bulletins through compact headers and request complete bodies separately. That retrieval behaviour belongs to the client/node protocol rather than to the bulletin object itself.

---

## 6. Relationships

The principal relationships are:

- a user authors messages;
- a message is addressed to one user;
- a user authors bulletins;
- a node stores messages and bulletins;
- clients act on behalf of a user when communicating with a node.

Clients and transports participate in communication but are not persistent domain entities in version 0.1.

---

## 7. Domain rules

- One normalized base callsign represents one OpenQSP user.
- Messages use `(recipient, mailbox sequence)` and bulletins use a node-local sequence.
- Version 0.1 objects are `Message` and `Bulletin`.
- Stored object content is immutable.
- A private message belongs to the recipient user's mailbox, not to a device or transport address.
- A bulletin is public and has no recipient.
- Transport-specific state does not alter object meaning.
- Client presentation groupings do not create domain entities.
- The node becomes authoritative for an object after accepting and durably storing it.

---

## 8. Explicitly excluded from version 0.1

The following concepts are not part of the initial domain:

- `Device`;
- `Delivery` as a persistent domain object;
- conversation or thread;
- synchronized read state;
- message editing or deletion;
- attachments or files;
- channels and groups;
- presence;
- node federation;
- node-to-node synchronization.

They may be introduced later only when a concrete protocol or product requirement justifies them.

## Runtime identity clarification (M6)

An account is the persistent normalized base-callsign identity. An authenticated session is ephemeral runtime state and is deliberately not a v0.1 persistent domain object. TCP disconnect removes its session and presence without changing its account or mailbox.
