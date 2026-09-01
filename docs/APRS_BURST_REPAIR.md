# APRS symmetric burst repair

OpenQSP uses transaction-level reliability for Q1 bursts instead of one APRS ACK per fragment.

## Control messages

Controls are APRS text-message bodies and do not carry an APRS message ID.

- `Q1A:TTT` — the complete Q1 transaction `TTT` was received.
- `Q1N:TTT:MMMM` — selectively retransmit the fragments whose bits are set in the 16-bit hexadecimal mask `MMMM`; bit 0 represents fragment 0.

Example: `Q1N:0A7:8012` requests fragments 1, 4 and 15.

## Client request -> server

The client transmits the complete Q1 burst. The server does not emit positive fragment ACKs.

If all fragments arrive, the normal Core response is the positive result. For `SEND_MESSAGE`, the durable `STORED` response closes the transaction; there is no additional `Q1A`.

If the burst is incomplete after the repair grace period, the server emits one `Q1N` mask. The client retransmits only the requested fragments. The server may repeat the same repair request until the transaction completes or expires.

## Server response -> client

The server sends all fragments for one logical response transaction in one burst and keeps at most one response transaction in flight per peer.

The client answers a complete response burst with one `Q1A`. If fragments are missing after the quiet/repair delay, it emits `Q1N` and the server retransmits only those fragments.

If a final `Q1A` is lost, the server eventually retries the burst; a client that has already completed that transaction repeats `Q1A` without delivering the Core response twice.

## Fallback

A server outbound transaction that receives neither `Q1A` nor `Q1N` falls back to a whole-burst retry after the existing APRS ACK timeout. This protects against loss of the control message itself.

## Local tests

Server:

```bash
cd server
python -m pytest tests/transport/test_aprs_selective_burst.py
python -m pytest
```

The companion OpenQSP-App PR must be used for RF/end-to-end testing so both ends understand `Q1A` and `Q1N`.
