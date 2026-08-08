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

#### 3.1.1 OpenQSP APRS service identity

The APRS service identity is **`OPENQSP`**.

`OPENQSP` is used as:

- the APRS-IS login name of the OpenQSP service;
- the APRS message addressee for traffic sent by users to the service;
- the APRS source address for traffic originated by the service.

The service therefore does not require a personal amateur callsign or SSID as an intermediate public identity. At the APRS layer the intended interaction is simply:

```text
EA3GNU  -> OPENQSP
OPENQSP -> EA3GNU
```

The normal APRS-IS passcode mechanism is used to establish a verified `OPENQSP` connection. Passcodes are deployment credentials and are not stored in this repository.

For a filtered APRS-IS connection, the service may request only APRS messages addressed to itself using:

```text
filter g/OPENQSP
```

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

### 3.7 APRS-IS experimental verification

The basic APRS-IS integration was manually verified on **2026-08-08** before implementation of the production transport adapter.

These tests were performed with small standalone Python programs outside the repository. The test code is intentionally not part of OpenQSP; only the verified behaviour is recorded here.

#### Test A — verified service login

A TCP connection was opened to the APRS-IS filtered port and the service logged in using `OPENQSP` as its login identity:

```text
user OPENQSP pass <passcode> vers OpenQSP-Test 0.1 filter g/OPENQSP
```

The APRS-IS server returned:

```text
# logresp OPENQSP verified, server T2GB
```

This verifies that `OPENQSP` can establish a normal **verified APRS-IS session** using the standard APRS-IS passcode mechanism. A personal callsign such as `EA3GNU-10` is therefore not required as the server identity.

#### Test B — filtered inbound message and service reply

A second verified APRS-IS client logged in as `EA3GNU` and injected the following APRS message directly into APRS-IS:

```text
EA3GNU>APRS,TCPIP*::OPENQSP  :HOLA OPENQSP
```

The OpenQSP echo test process was connected as `OPENQSP` with:

```text
filter g/OPENQSP
```

It received the message addressed to `OPENQSP` and injected a reply with `OPENQSP` as the APRS source:

```text
OPENQSP>APOQSP,TCPIP*::EA3GNU   :MESSAGE OK: HOLA OPENQSP
```

The `EA3GNU` APRS-IS client received the resulting packet as:

```text
OPENQSP>APOQSP,TCPIP*,qAC,T2SPAIN::EA3GNU   :MESSAGE OK: HOLA OPENQSP
```

This verifies the complete Internet-only path:

```text
EA3GNU -> APRS-IS -> OPENQSP -> APRS-IS -> EA3GNU
```

No RF transmission, digipeater or IGate was involved in this test.

#### Test C — Tier-2 server observation

An initial test used `rotate.aprs2.net` independently for both clients. The connections were assigned to different Tier-2 servers (`T2GB` and `T2SPAIN`) and the expected message was not observed by the `OPENQSP` test process during that run.

When both clients were connected to `T2SPAIN`, the bidirectional test succeeded immediately.

This observation **does not establish a protocol requirement that both endpoints use the same Tier-2 server**. Normal APRS-IS operation must not depend on that assumption. Cross-server propagation and the correct production server-selection strategy therefore remain an explicit item to verify before the APRS transport is considered production-ready.

#### Test D — APRS message IDs and bidirectional ACK

A complete APRS acknowledgement exchange was then verified over direct APRS-IS connections.

The `EA3GNU` test client sent a message addressed to `OPENQSP` with APRS message ID `01`:

```text
EA3GNU>APRS,TCPIP*::OPENQSP  :HOLA OPENQSP{01
```

The `OPENQSP` process received the message and replied with the transport-level acknowledgement:

```text
OPENQSP>APOQSP,TCPIP*::EA3GNU   :ack01
```

The client received the resulting APRS-IS packet and successfully correlated the acknowledgement with its outgoing message ID `01`.

The service then sent its echo response with its own APRS message ID:

```text
OPENQSP>APOQSP,TCPIP*::EA3GNU   :MESSAGE OK: HOLA OPENQSP{01
```

The client received that message, extracted its message ID, and returned the matching acknowledgement:

```text
EA3GNU>APRS,TCPIP*::OPENQSP  :ack01
```

The client-side test reported:

```text
Incoming message ACK: OK
Echo response:        OK
```

This verifies the complete transport-level message-ID/ACK cycle in both directions:

```text
EA3GNU  -> OPENQSP : HOLA OPENQSP{01
OPENQSP -> EA3GNU  : ack01
OPENQSP -> EA3GNU  : MESSAGE OK: HOLA OPENQSP{01
EA3GNU  -> OPENQSP : ack01
```

The fact that both test directions used ID `01` is not a requirement and does not imply a shared global ID space. Production code must correlate APRS message IDs with the relevant peer and pending outbound message state.

This ACK is an **APRS transport-level acknowledgement**. It confirms reception of the APRS message packet and remains distinct from OpenQSP application-level acknowledgements such as `ACK_OBJECT`.

#### Verified conclusions

The tests establish that:

- `OPENQSP` is accepted as an APRS-IS login identity;
- the `OPENQSP` login can be verified using the standard APRS-IS passcode mechanism;
- `g/OPENQSP` can be used to restrict the service feed to messages addressed to `OPENQSP` in the tested configuration;
- users can address APRS messages directly to `OPENQSP`;
- the service can originate APRS messages with `OPENQSP` as the source;
- bidirectional APRS messaging works without any personal server callsign appearing in the public message flow;
- direct APRS-IS injection is sufficient for development testing without RF coverage;
- APRS message IDs are successfully preserved and parsed in both directions;
- APRS transport-level acknowledgements (`ack<ID>`) work from service to user and from user to service.

The following remain to be validated separately:

- retry timing and retry limits when an APRS ACK is not received;
- duplicate handling and idempotent processing after retries;
- message size and fragmentation policy for OpenQSP frames;
- RF -> IGate -> APRS-IS -> OpenQSP operation;
- OpenQSP -> APRS-IS -> IGate -> RF operation;
- reliable cross-server behaviour when clients and IGates enter APRS-IS through different servers.

---

## 4. Future transports

Packet, LoRa, serial, Bluetooth and other transports may define their own connection, activity and delivery policies while carrying the same OpenQSP application frames.
