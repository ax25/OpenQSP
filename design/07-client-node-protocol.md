# 07 - Client / Node Protocol

## Objective

This document defines the logical commands, responses and conversation between an OpenQSP client and an OpenQSP BBS node.

It does not define binary encoding. The binary representation of these commands and responses belongs in a later document.

---

## 1. Communication model

OpenQSP version 1 follows a traditional BBS model:

- clients always communicate with a BBS node;
- clients never exchange OpenQSP data directly with other clients;
- the node stores private messages and bulletins;
- the node answers queries and accepts new content;
- federation and node-to-node synchronization are out of scope for version 1.

---

## 2. General principles

- Commands are logically independent.
- Each command produces a defined response.
- A client keeps a local database of downloaded data.
- Clients should request incremental changes instead of the complete BBS state.
- Private messages and bulletins intentionally use different retrieval patterns.
- Transport-specific session and activity behaviour remains defined in `04-transports.md`.

---

## 3. Identity

The client acts as one OpenQSP user. Callsign normalization and the complete identity rules are defined in `06-object-model.md`.

---

## 4. Private messages

Private messages behave like persistent SMS messages. They:

- have no title or subject;
- have no conversation or thread identifier;
- are short text messages;
- are always downloaded in full.

A private message contains:

- `sequence`;
- `from`;
- `to`;
- `created_at`;
- `body`.

The maximum body size remains undecided.

### 4.1 SEND_MESSAGE

`SEND_MESSAGE` submits a private message for durable storage.

Input:

- `created_at`;
- `recipient`;
- `body`.

The authenticated or transport-verified user is the author. The client does not supply a separate author identity.

The request contains no message identifier, author or transport transaction identifier. The
node atomically stores the message and assigns the next sequence in the recipient mailbox.

The successful response is `STORED`: the operation committed durably. It carries no message
identifier. Failures use `ERROR` as established in `03-protocol.md`.

### 4.2 GET_NEW_MESSAGES

`GET_NEW_MESSAGES` requests private messages newer than the client's current synchronization point.

Parameters:

- `since`: the last mailbox sequence known by the client;
- `max`: the maximum number of messages requested.

`since` is an unsigned 32-bit cursor in the authenticated user's mailbox. `since=0` means no
previous state. `GET_NEW_MESSAGES since=17` means to return that mailbox's messages whose
sequence is greater than 17. The mailbox context is part of the cursor's meaning.

The node returns complete private messages, not headers.

Example logical exchange:

```text
Client:
GET_NEW_MESSAGES
SINCE 124
MAX 5

Node:
MESSAGE
SEQUENCE 125
FROM EA1ABC
DATE ...
BODY Hola, ¿estás disponible esta tarde?

MESSAGE
SEQUENCE 126
FROM EA5XYZ
DATE ...
BODY He probado la nueva versión.

END
```

There is no `GET_MESSAGE` command in version 1. There are no private-message headers. Every returned message includes its complete body.

---

## 5. Bulletins

Bulletins may be much longer than private messages. Their retrieval therefore uses two phases: the client first requests headers and then requests the complete bulletins it wants.

A bulletin contains:

- `sequence`;
- `author`;
- `created_at`;
- `title`;
- `body`.

### 5.1 GET_NEW_BULLETINS

`GET_NEW_BULLETINS` requests bulletin headers newer than the client's current synchronization point.

Parameters:

- `since`: the last bulletin synchronization point known by the client;
- `max`: the maximum number of bulletin headers requested.

The response contains bulletin headers only. Each header contains:

- `sequence`;
- `author`;
- `created_at`;
- `title`.

The title is mandatory because a sequence alone is not useful to the user.

Example logical exchange:

```text
Client:
GET_NEW_BULLETINS
SINCE 245
MAX 5

Node:
BULLETIN_HEADER
SEQUENCE 246
AUTHOR EA1ABC
DATE ...
TITLE Concurso VHF septiembre

BULLETIN_HEADER
SEQUENCE 247
AUTHOR EA3GNU
DATE ...
TITLE Nueva versión OpenQSP

END
```

### 5.2 GET_BULLETIN

`GET_BULLETIN` requests one complete bulletin.

Input:

- `sequence`.

A successful response contains the complete bulletin:

```text
BULLETIN
SEQUENCE ...
AUTHOR ...
DATE ...
TITLE ...
BODY ...
```

If the bulletin does not exist, the node returns `ERROR / NOT_FOUND`, or the equivalent protocol error defined by `03-protocol.md` when that error is assigned a binary representation.

---

## 6. Incremental synchronization

The client maintains local synchronization state and requests only data newer than its last known synchronization point. For example:

```text
GET_NEW_MESSAGES SINCE 124
GET_NEW_BULLETINS SINCE 245
```

Incremental synchronization reduces APRS traffic. It also avoids repeatedly downloading existing data over Internet transports.

Message cursors use the recipient mailbox's unsigned 32-bit sequence space. Bulletin cursors
use one node-local unsigned 32-bit sequence space. `END.next_since` uses the corresponding
space. Wraparound and retention policy remain future details.

---

## 7. END marker

A multi-item response uses an `END` marker to indicate that the response is complete. This applies to responses to:

- `GET_NEW_MESSAGES`;
- `GET_NEW_BULLETINS`.

`END` is a logical response marker. Its binary representation will be defined later.

---

## 8. Activity interaction

Valid client requests may refresh user activity according to the transport rules. Node-originated deliveries do not themselves prove client activity. The canonical activity rules, including the APRS activity algorithm, are in `04-transports.md`.

---

## 9. Proactive delivery

While the transport considers a user active, the node may proactively send:

- a complete new private message;
- a new bulletin header.

Proactive delivery is optional node behaviour governed by transport policy. It is not required, and it does not introduce subscriptions.

---

## 10. Out of scope

The following are out of scope for version 1 or deferred to later specifications:

- message subjects;
- message threads;
- message editing;
- message deletion;
- read receipts;
- bulletin comments;
- files;
- groups;
- chat rooms;
- federation;
- node-to-node synchronization;
- binary encoding;
- maximum private-message size.

## Capability discovery (M6)

`GET_CAPABILITIES` is an authenticated, transport-independent request returning one deterministic `CAPABILITIES` response. The returned protocol version and bit set allow clients to enable private messaging, bulletin listing/retrieval, and proactive message display only when implemented. Unsupported operation codes deterministically produce the existing `UNKNOWN_OPERATION` error; authorization, invalid fields, cursors, missing bulletins, and rejected requests retain their documented error codes.
