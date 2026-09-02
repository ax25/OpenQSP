# OpenQSP APRS carriage V2

V2 optimizes OpenQSP for slow APRS RF links while keeping the Core binary frame unchanged.

## DATA: Q2

A DATA fragment is an unnumbered APRS message body:

```text
Q2<BASE91>
```

`BASE91` uses the 91 printable ASCII characters from `!` through `~` except `{`, `|`, and `~`. The decoded payload is:

```text
transaction_id      u8
fragment_descriptor u8
core_bytes          1..50 bytes
```

The descriptor packs `fragment_index` in the high nibble and `fragment_total - 1` in the low nibble. V2 therefore supports 1..16 fragments. The transaction identifier is ephemeral per peer and wraps in an 8-bit space.

The maximum APRS message body remains 67 characters. A 50-byte Core chunk plus the two-byte Q2 header encodes within that bound.

Q2 fragments do not carry `{APRS-ID}` and therefore do not generate native APRS per-fragment ACKs.

## Transaction controls

Positive receipt of a complete outbound transaction is:

```text
A2<BASE91(transaction_id:u8)>
```

Selective repair is:

```text
N2<BASE91(transaction_id:u8 + missing_bitmap:u16)>
```

Bit `n` in the bitmap requests retransmission of fragment `n`. A receiver waits for the burst quiet period before requesting repair: 5 seconds after the latest non-final fragment, or 2 seconds once the final fragment has been observed.

A successful inbound `SEND_MESSAGE` is closed directly with the durable compact result:

```text
S2<BASE91(transaction_id:u8)>
```

`S2` means the Core committed the message durably. It is not interchangeable with `A2`, which only confirms receipt of an outbound transaction. Failed `SEND_MESSAGE` operations continue to return a normal Q2-encoded Core `ERROR` frame so error details are preserved.

## Compatibility

The legacy Q1 Base64url carriage remains parseable during migration. Q1A/Q1N controls are also accepted, but the selective-burst server emits Q2/A2/N2/S2.

## Efficiency

Q1 carries at most 48 Base64url characters per fragment, representing 36 Core bytes. Q2 carries up to 50 raw Core bytes per fragment. A maximum current `SEND_MESSAGE` frame with a six-character recipient is 224 bytes, which requires 7 Q1 fragments but only 5 Q2 fragments. Native APRS fragment ACKs are also eliminated.
