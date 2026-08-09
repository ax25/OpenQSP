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

Live APRS-IS acceptance completed successfully on 2026-08-09. The exercised
production path covered verified service login, `GET_CAPABILITIES`, fragmented
`SEND_MESSAGE` with durable `STORED`, mailbox retrieval after a full node
restart, unsolicited proactive `MESSAGE` delivery while the recipient was
ACTIVE, a forced TCP disconnect followed by automatic APRS-IS reconnection and
successful post-reconnect requests, and deliberate cross-server traffic between
EA3GNU on T2UK and OPENQSP on T2RADOM. Detailed evidence is recorded in
`M7-live-aprsis-acceptance.md`.

RF/IGate validation remains an environment-dependent field follow-up. It is not
required for M7 completion because the APRS carriage, retry, replay, persistence,
proactive-delivery and APRS-IS network paths have all been accepted independently.

On APRS-IS connection loss, queued packets, pending fragment ACK correlation,
and immediate ACK output are discarded because they belong to the lost socket.
Bounded reassembly and completed-request replay entries remain until their TTL:
they are keyed by full peer and transaction rather than a socket, allowing a
radio peer to finish or safely replay a request after service reconnection.
Neither choice changes durable Core state.

Canonical large vectors are derived and checked with production
`encode_frame_text`, `fragment_frame`, and `decode_frame_text`. A retry retains
its `TTT` and APRS fragment IDs; a new request uses a new `TTT`. Neither is a
mailbox sequence or object identity.
