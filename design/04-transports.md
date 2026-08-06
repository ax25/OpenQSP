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

## 2. Internet

Internet transports such as TCP or WebSocket may maintain a persistent connection. The transport maps each complete OpenQSP frame to an ordered, reliable byte stream or message and preserves frame boundaries when required by the underlying API.

While the connection is available, the server may deliver new messages or bulletin notifications immediately without waiting for a new `GET` request.

Connection authentication, frame encapsulation, keepalive, reconnection and connection-lifetime policy are implementation concerns and will be specified when the Internet transport is implemented. A connection is not an OpenQSP user identity, and opening or closing one does not alter stored objects.

---

## 3. APRS

APRS is a low-bandwidth, connectionless transport. OpenQSP must minimize unnecessary polling while still allowing timely delivery of new information.

### 3.1 APRS address and OpenQSP identity

An APRS address may contain an SSID, for example `EA3GNU-10`.

The SSID is transport addressing only. It does not create a separate OpenQSP user. Identity normalization is defined in `06-object-model.md`.

A node may remember the most recently usable APRS address for an OpenQSP user in order to deliver frames, but that address is not stored inside messages or bulletins.

### 3.2 User activity

Each node maintains a temporary activity timer for each user communicating through APRS. This timer is operational state in the APRS transport layer, not a session or presence protocol.

User activity is inferred from normal protocol usage. Any valid request received from a user refreshes that user's activity timer. Examples include, but are not limited to:

- `GET_NEW_MESSAGES`;
- `GET_NEW_BULLETINS`;
- `GET_BULLETIN`;
- `SEND_MESSAGE`;
- `POST_BULLETIN`;
- `ACK` or another valid client acknowledgement request.

This list is illustrative only. Any future valid client request also refreshes activity unless that operation is explicitly documented otherwise.

Frames originated by the node, including `MESSAGE`, `BULLETIN`, `NEW_MESSAGE` or `NEW_BULLETIN` notifications, **MUST NOT** refresh user activity. Only receipt of a valid client request can refresh the timer; malformed, rejected or unrelated transport traffic cannot do so.

The exact timeout is configurable and is not fixed in version 0.1.

### 3.3 Proactive delivery while active

While a user's APRS activity timer remains valid, the node **MAY** proactively send newly available information to that user without requiring another explicit polling request.

This may include, according to node policy:

- complete newly arrived private messages;
- new bulletin headers;
- other version-compatible novelty notifications defined later.

Version 0.1 does not define subscriptions. Being active only makes proactive delivery possible; node policy decides which novelties are sent.

### 3.4 Loss of activity

If the node sends a proactive APRS delivery and receives no required response or acknowledgement, it may retry according to APRS policy.

When the activity timer expires, the node stops treating the user as active and stops sending unsolicited updates. Delivery of information in response to an explicit request is unaffected.

The next valid request from that user makes the user active again.

### 3.5 Local state only

APRS activity is **LOCAL TO EACH NODE** and **MUST NEVER** be synchronized between nodes. It belongs to the APRS transport layer and is not part of the Object Model.

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
