# OpenQSP APRS carriage profile v0.1

APRS carries the **unchanged complete binary OpenQSP frame** as unpadded
Base64url, split into chunks of at most 48 characters:

```text
Q1:<TTT>:<II>/<NN>:<DATA>{<APRS-ID>
```

`TTT` is three uppercase base36 characters. `II` and `NN` are two uppercase
base36 characters; indexes are zero based and `NN` is 1–16. The native APRS
message ID is outside `DATA`. The canonical `GET_CAPABILITIES` frame
`01050000` is Base64url `AQUAAA`:

```text
EA3AAA>APRS,TCPIP*::OPENQSP  :Q1:0A7:00/01:AQUAAA{4F
OPENQSP>APOQSP,TCPIP*::EA3AAA   :ack4F
```

The ACK says only that this APRS fragment arrived. OpenQSP `STORED` says Core
committed a message durably; the acknowledgements are never interchangeable.

## Reliability, ordering, and limits

Fragments reassemble by `(full APRS source, TTT)`, in any order. Exact
duplicates are harmless; conflicting data or totals invalidate a transaction.
Incomplete state expires. A bounded, short-lived replay cache makes an
identical completed-request retry replay the ordered Core result without a
second Core call; different bytes under the same key conflict. APRS and
transaction IDs remain ephemeral and never enter stored objects.

Defaults are an 8-second ACK timeout, three total fragment attempts, a
two-second per-peer send interval, a 10-minute activity interval, 16 fragments,
and bounded queues/caches. Explicit responses precede best-effort unsolicited
mail. Delivery failure never removes durable mail; synchronization remains
authoritative.

## Identity and security

`EA3GNU-10` addresses the APRS endpoint while Core sees `EA3GNU`. Different
SSIDs retain independent activity/routing state. APRS source callsigns are
**transport-asserted and not cryptographically authenticated**. Account
passwords must not be sent over APRS.

## APRS-IS operation and validation boundary

The passcode is supplied externally. The service logs in as `OPENQSP`, requests
`filter g/OPENQSP`, requires a verified `# logresp` in production, and
reconnects after disconnect. Host, port, path, and credentials are configurable.
The 2026-08-08 Internet-only laboratory run in `04-transports.md` succeeded; an
independently rotated cross-server attempt was inconclusive. Deployments should
use a stable Tier-2 endpoint and verify cross-server visibility, but neither
Core nor this profile assumes same-server placement. RF/IGate validation is an
environment-dependent follow-up.

Canonical large vectors are derived and checked with production
`encode_frame_text`, `fragment_frame`, and `decode_frame_text`. A retry retains
its `TTT` and APRS fragment IDs; a new request uses a new `TTT`. Neither is a
mailbox sequence or object identity.
