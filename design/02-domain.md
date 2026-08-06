# OpenQSP Domain Model

> This document defines the conceptual entities that exist in OpenQSP.

It does not describe implementation details, database schemas, APIs or transport-specific packet formats.

---

# Domain Overview

The initial OpenQSP domain is intentionally small.

Its core entities are:

- User
- Message
- Delivery
- Bulletin
- Device

`Conversation` is not a core domain entity. Conversations may be derived by clients for presentation purposes, for example by grouping messages by sender, recipient, subject or thread identifier.

`Device` is a synchronization entity rather than a primary communication entity.

```text
User -------- sender/recipient -------- Message
                                         |
                                         |
                                         v
                                      Delivery

User ------------------------------- Device

Bulletin is published independently to multiple users.
```

---

# User

## Description

Represents an amateur radio identity within OpenQSP.

A user exists independently of the transport currently being used. The same user may communicate through Internet, APRS, AX.25 Packet, LoRa, VARA or future transports.

## Conceptual Attributes

- Stable internal identifier
- Amateur radio callsign
- Profile information
- Preferences
- Account status

## Relationships

A user may:

- Send messages
- Receive messages
- Own multiple devices
- Publish or receive bulletins, depending on permissions

A user does not own messages as subordinate objects. A user participates in a message as sender, recipient or another future participant role.

---

# Message

## Description

Represents one persistent unit of communication.

A message is independent of the transport used to submit or deliver it.

After the server accepts a message, its communication content is immutable. Corrections or retractions should be represented as new operations rather than silently modifying the accepted content.

## Conceptual Attributes

- Stable unique identifier
- Sender
- One or more recipients, if supported by the message type
- Content
- Creation time
- Server acceptance time
- Priority
- Message type
- Optional expiration policy

## Responsibilities

A message represents:

- What was communicated
- Who originated it
- Who it is intended for

A message does not represent:

- A specific transport attempt
- Delivery progress
- Device synchronization state
- Presentation grouping

Delivery state is represented by separate `Delivery` entities.

---

# Delivery

## Description

Represents one delivery operation for one message toward one destination through one transport.

A message may have multiple deliveries. This allows the same message to be attempted through different transports, retried, or delivered independently to several devices or destinations.

## Conceptual Attributes

- Stable unique identifier
- Message reference
- Destination
- Selected transport
- Current state
- Attempt count
- Creation time
- Last attempt time
- Confirmation time, when applicable
- Failure information, when applicable

## Example

```text
Message M-105

├── Delivery D-1 → EA4ABC via Internet → delivered
├── Delivery D-2 → EA4ABC via APRS     → queued
└── Delivery D-3 → EA4ABC via Packet   → failed
```

## Responsibilities

A delivery represents:

- How a message is being delivered
- Where it is being delivered
- The progress and outcome of that delivery

A delivery does not modify the meaning or content of the message.

---

# Bulletin

## Description

Represents persistent published information intended for multiple users rather than a private recipient.

Bulletins may belong to a topic, channel or category and are normally discovered through compact listings before their full content is requested.

## Conceptual Attributes

- Stable unique identifier
- Publisher
- Title
- Content
- Category or channel
- Publication time
- Priority
- Optional expiration time

## Responsibilities

A bulletin represents published information.

The mechanism used to list, request, synchronize or transport bulletins belongs to the protocol and transport layers, not to the bulletin entity itself.

---

# Device

## Description

Represents one client installation or endpoint participating in synchronization for a user.

Examples include:

- An Android application installation
- An iOS application installation
- A Windows client
- A Linux client
- A web client session, if persistent device identity is required

## Conceptual Attributes

- Stable device identifier
- User reference
- Device name or label
- Client type
- Last synchronization position
- Last known activity
- Notification or delivery capabilities

## Responsibilities

A device tracks synchronization-specific state, such as which changes have already been received.

A device does not define the user's identity and is not the destination of a radio message unless a future protocol feature explicitly targets individual devices.

---

# Relationships

```text
                         +-------------+
                         |    User     |
                         +------+------+ 
                                |
                    owns        |        participates as
                                |        sender/recipient
                                v                 |
                         +-------------+          |
                         |   Device    |          |
                         +-------------+          v
                                           +-------------+
                                           |   Message   |
                                           +------+------+ 
                                                  |
                                      delivered through
                                                  |
                                                  v
                                           +-------------+
                                           |  Delivery   |
                                           +-------------+

                         +-------------+
                         |  Bulletin   |
                         +-------------+
```

---

# Domain Rules

- Every core entity has a stable identifier independent of transport.
- A message and its deliveries are separate entities.
- A message may exist before any delivery is created.
- Multiple deliveries may refer to the same message.
- Transport-specific state belongs to `Delivery`, not `Message`.
- Client presentation groupings do not alter the domain model.
- Devices maintain synchronization state independently.
- Clients may create and persist data while offline until synchronization is possible.
- Once accepted by the server, shared system state is coordinated by the server.

---

# Deferred Entities

The following concepts may be introduced later if they become necessary:

- Attachment
- Channel
- Group
- Presence
- Notification
- Federation peer
- Thread or conversation identifier

They are intentionally excluded from the initial model to keep the domain small and avoid designing features before they are required.

---

# Open Questions

- Whether messages support multiple recipients in the first protocol version.
- Whether callsigns are permanent user identifiers or mutable identity attributes.
- How secondary station identifiers and SSIDs relate to a user.
- Whether bulletin channels are entities or simple bulletin attributes.
- Whether message expiration removes content or only stops further delivery attempts.
