# OpenQSP Transports

## Purpose

This document defines how OpenQSP behaves over different transports.

The application operations and binary frames are defined in `03-protocol.md`. User identity and object semantics are defined in `06-object-model.md`.

A transport carries OpenQSP frames without changing their application meaning.

---

## 1. Common responsibilities

A transport adapter may provide:

- transport addressing;
- framing or text-safe encoding;
- fragmentation and reassembly;
- link-level acknowledgements;
- retries and rate limiting;
- connection management.

These mechanisms are separate from `ACK_OBJECT`, which confirms an application-level durable processing result.

---

## 2. Internet transport

Internet transports such as TCP or WebSocket may maintain a persistent connection.

While the connection is available, the server may deliver new messages or bulletin notifications immediately without waiting for a new `GET` request.

Connection authentication, keepalive and reconnection policy are implementation concerns and will be specified when the Internet transport is implemented.

---

## 3. APRS transport

APRS is a low-bandwidth, connectionless transport. OpenQSP must minimize unnecessary polling while still allowing timely delivery of new information.

### 3.1 APRS address and OpenQSP identity

An APRS address may contain an SSID, for example `EA3GNU-10`.

The SSID is transport addressing only. It does not create a separate OpenQSP user. Identity normalization is defined in `06-object-model.md`.

A node may remember the most recently usable APRS address for an OpenQSP user in order to deliver frames, but that address is not stored inside messages or bulletins.

### 3.2 Active user state

Each node maintains a local, temporary activity record for users communicating through APRS.

A successfully received and valid OpenQSP request from a user refreshes that user's APRS activity timer. Examples include:

- `GET_MESSAGES`;
- `GET_BULLETIN_HEADERS`;
- `GET_BULLETIN`;
- `SEND_MESSAGE`;
- `POST_BULLETIN`;
- acknowledgements or other valid responses.

The exact timeout is configurable and is not fixed in version 0.1.

### 3.3 Proactive delivery while active

While a user's APRS activity timer remains valid, the node may send newly available information to that user without requiring another explicit polling request.

This may include, according to node policy:

- newly arrived private messages;
- notice that new bulletin headers are available;
- other version-compatible novelty notifications defined later.

Version 0.1 does not define subscriptions. Being active only makes proactive delivery possible; node policy decides which novelties are sent.

### 3.4 Loss of activity

If the node sends a proactive APRS delivery and receives no required response or acknowledgement, it may retry according to APRS policy.

After the configured timeout, failed delivery policy or both, the node stops treating the user as active and stops unsolicited delivery.

The next valid request from that user makes the user active again.

### 3.5 Local state only

APRS activity is local operational state of one node.

It is not:

- part of the user identity;
- stored in messages or bulletins;
- synchronized between nodes;
- a global online/offline presence indicator.

Two nodes may legitimately hold different activity states for the same user.

### 3.6 Rate control

Proactive APRS delivery must be rate-limited and must respect channel capacity, duplicate suppression and transport rules.

Detailed timing, retry count, fragmentation and APRS text-safe encoding remain to be specified in a dedicated APRS transport profile.

---

## 4. Future transports

Packet, LoRa, serial, Bluetooth and other transports may define their own connection, activity and delivery policies while carrying the same OpenQSP application frames.
