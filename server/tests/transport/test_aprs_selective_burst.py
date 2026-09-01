from __future__ import annotations

from openqsp.protocol import GetCapabilities, encode_frame
from openqsp.server import ServerCore
from openqsp.transport.aprs import (
    AdapterConfig,
    SelectiveBurstAPRSAdapter,
    encode_burst_ack,
    encode_missing,
    parse_burst_control,
)
from openqsp.transport.aprs.carriage import fragment_frame, parse_fragment


def test_burst_control_round_trip() -> None:
    assert parse_burst_control(encode_burst_ack("0A7")) == (
        "ack",
        "0A7",
        frozenset(),
    )
    body = encode_missing("0A7", {1, 4, 15})
    assert body == "Q1N:0A7:8012"
    assert parse_burst_control(body) == (
        "missing",
        "0A7",
        frozenset({1, 4, 15}),
    )


def test_complete_outbound_transaction_needs_one_transaction_ack() -> None:
    adapter = SelectiveBurstAPRSAdapter(
        ServerCore(), config=AdapterConfig(min_interval=0)
    )
    transaction = adapter.queue_frame("EA3AAA", encode_frame(GetCapabilities()))

    burst = adapter.poll(now=0)

    assert burst
    assert all(parse_fragment(packet.body).message_id is None for packet in burst)
    assert adapter.pending_count == len(burst)
    assert adapter.receive("EA3AAA", encode_burst_ack(transaction), now=0) == "acknowledged"
    assert adapter.pending_count == 0


def test_missing_control_retransmits_only_requested_fragments() -> None:
    adapter = SelectiveBurstAPRSAdapter(
        ServerCore(),
        config=AdapterConfig(ack_timeout=31, max_attempts=3, min_interval=0),
    )
    transaction = adapter.queue_frame("EA3AAA", encode_frame(GetCapabilities()))
    first = adapter.poll(now=0)
    fragments = [parse_fragment(packet.body) for packet in first]
    missing_index = len(fragments) - 1

    assert (
        adapter.receive(
            "EA3AAA", encode_missing(transaction, {missing_index}), now=0
        )
        == "repair-requested"
    )
    repair = adapter.poll(now=0)

    assert len(repair) == 1
    repaired = parse_fragment(repair[0].body)
    assert repaired.transaction_id == transaction
    assert repaired.index == missing_index


def test_selective_repair_does_not_fall_back_to_full_burst_on_timeout() -> None:
    adapter = SelectiveBurstAPRSAdapter(
        ServerCore(),
        config=AdapterConfig(ack_timeout=31, max_attempts=4, min_interval=0),
    )
    frame = bytes(range(160))
    transaction = adapter.queue_frame("EA3AAA", frame)
    first = adapter.poll(now=0)
    assert len(first) > 1

    assert adapter.receive("EA3AAA", encode_missing(transaction, {0}), now=1) == (
        "repair-requested"
    )
    repair = adapter.poll(now=1)
    assert len(repair) == 1
    assert parse_fragment(repair[0].body).index == 0

    # Reproduce the live failure: once the peer has explicitly said that only
    # fragment 0 is missing, expiry of the normal ACK timeout must not resend
    # the entire transaction.  The receiver will send another Q1N if repair is
    # still required.
    assert adapter.poll(now=32) == []

    assert adapter.receive("EA3AAA", encode_missing(transaction, {0}), now=33) == (
        "repair-requested"
    )
    second_repair = adapter.poll(now=33)
    assert len(second_repair) == 1
    assert parse_fragment(second_repair[0].body).index == 0


def test_incomplete_inbound_burst_emits_one_missing_mask_not_fragment_acks() -> None:
    adapter = SelectiveBurstAPRSAdapter(
        ServerCore(), config=AdapterConfig(min_interval=0), repair_grace=1
    )
    frame = encode_frame(GetCapabilities())
    original = fragment_frame(frame, "ABC")[0]
    first = type(original)("ABC", 0, 2, original.data, None)

    assert adapter.receive("EA3AAA", first.body, now=0) == "fragment"
    assert adapter.poll(now=0) == []
    control = adapter.poll(now=1)

    assert len(control) == 1
    assert control[0].body == "Q1N:ABC:0002"
    assert not control[0].body.startswith("ack")
