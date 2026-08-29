# Per-user transport selection

This document defines the server-side policy for choosing how OpenQSP contacts a user when more than one transport exists.

## Principle

The server keeps one **current preferred transport per OpenQSP user** for proactive delivery. The preference is operational routing state; it is not part of the user's identity and is not stored inside messages or bulletins.

The preferred transport is selected by the transport through which the user most recently establishes valid communication with the server.

## APRS becomes preferred after valid APRS communication

When the server receives a valid OpenQSP request from a user through APRS, that user becomes **APRS-preferred**.

While the user remains APRS-preferred:

- newly available messages intended for that user should be delivered proactively through APRS;
- the server should not also attempt proactive Internet delivery merely because an old Internet/WebSocket connection still exists;
- normal APRS acknowledgement, retry, rate-limit and delivery-state rules apply;
- the APRS address/SSID most recently proven usable may be kept as transport-local routing state.

A user remains considered reachable through APRS until repeated delivery failures provide sufficient evidence that APRS communication with that user is no longer working. A single lost packet or isolated timeout must not immediately switch the user away from APRS.

The exact failure threshold, timeout and backoff policy are implementation details, but the required semantic is that **successful APRS communication selects APRS, and repeated APRS failures can eventually clear APRS reachability**.

## Internet immediately becomes preferred after valid Internet communication

When the same user later communicates successfully with the server through the Internet API, WebSocket, TCP, or another authenticated Internet transport, that user becomes **Internet-preferred immediately**.

While the user is Internet-preferred:

- proactive messages should be delivered through the active Internet transport;
- the server must not proactively contact that user through APRS;
- previously remembered APRS routing information may be retained as transport-local state, but it is not used for proactive delivery while Internet remains preferred.

In particular, an Internet reconnection is an explicit signal that the client has returned to Internet mode. The server must therefore stop treating recent APRS activity as permission to keep sending unsolicited APRS traffic.

## Switching rule

The intended state transition is:

```text
valid APRS request from USER
    -> preferred_transport(USER) = APRS

valid authenticated Internet communication from USER
    -> preferred_transport(USER) = INTERNET

repeated APRS delivery failure while APRS-preferred
    -> APRS reachability is cleared according to server policy
```

If the user later communicates through APRS again, APRS becomes preferred again.

## Delivery and persistence

Transport selection changes only how the server attempts delivery. Messages remain durably stored in the OpenQSP Core independently of transport.

A transport failure must never delete or lose a stored message. If proactive delivery fails, normal mailbox synchronization remains authoritative when the user next reconnects.

## Scope

This document defines required routing behaviour, not the implementation mechanism. The implementation may use an in-memory presence/routing registry, timestamps, transport sessions, or another bounded operational structure, provided that the externally visible behaviour follows the rules above.
