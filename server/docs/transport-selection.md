# Per-user transport selection (MVP)

The server keeps one **authoritative active transport per callsign** for
proactive delivery. Presence is operational routing state and is not stored on
messages. The only MVP values are `websocket`, `aprs`, and no active transport;
TCP is not part of this routing system.

## Explicit presence

- A successfully authenticated WebSocket connection selects `websocket` and
  records its unique session ID.
- An application or service may explicitly select `aprs` and record the full
  APRS endpoint (for example, `EA3GNU-7`). Observing APRS or APRS-IS traffic is
  not sufficient to select APRS.
- Selecting either transport replaces the previous selection. There is no
  automatic fallback between transports.
- A new WebSocket session supersedes the old session for the same callsign.
  Cleanup from an old session is conditional on its session ID, so a late
  disconnect cannot erase a newer session.

Presence is currently process-local. Durable message and delivery/read state
remain in the existing stores and are the source of truth across restarts.

## Delivery routing

For every newly stored message, the delivery router reads the recipient's
current presence exactly once:

```text
websocket -> attempt the authoritative WebSocket session
aprs      -> delegate to the APRS adapter using the recorded endpoint
none      -> do not attempt immediate delivery
```

Storage happens before this best-effort routing step. A missing route or a
transport failure therefore leaves the message available through the existing
mailbox/synchronization flow; it does not create a second pending-message
system. The message schema remains transport-independent.
