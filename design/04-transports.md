# Transport bindings

Core deliberately does not provide packet retry identity.

TCP and WebSocket carry a Core frame over a reliable ordered byte stream:

```text
Core frame
    ↓
reliable ordered transport
```

No OpenQSP message transaction ID is required for retransmission.

APRS carries Core beneath a transport envelope:

```text
transport envelope / APRS message ID
    ↓
Core frame
```

Native APRS message IDs and `ack<ID>` are transport facilities. A future APRS
adapter may implement peer-scoped IDs, ACKs, retry windows, duplicate
suppression, replay of a cached application result, and fragmentation or
reassembly. That ledger is intentionally deferred; its identifiers must never
become Message or Bulletin fields.

```text
APRS ack<ID>   transport packet received
OpenQSP STORED application data durably committed
```

An APRS transport ACK does not imply durable application storage. Conversely,
`STORED` is not an instruction to stop an APRS packet retry unless the adapter's
own transaction state associates that application result with its envelope.
