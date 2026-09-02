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


def test_default_repair_grace_waits_five_seconds_after_latest_nonfinal_fragment() -> None:
    adapter = SelectiveBurstAPRSAdapter(
        ServerCore(), config=AdapterConfig(min_interval=0)
    )
    frame = encode_frame(GetCapabilities())
    original = fragment_frame(frame, "ABC")[0]
    first = type(original)("ABC", 0, 4, original.data, None)
    second = type(original)("ABC", 1, 4, original.data, None)

    assert adapter.receive("EA3AAA", first.body, now=0) == "fragment"
    assert adapter.poll(now=4.99) == []
    assert adapter.receive("EA3AAA", second.body, now=4.99) == "fragment"
    assert adapter.poll(now=9.98) == []

    control = adapter.poll(now=9.99)
    assert len(control) == 1
    assert control[0].body == "Q1N:ABC:000C"


def test_final_fragment_shortens_missing_repair_grace_to_two_seconds() -> None:
    adapter = SelectiveBurstAPRSAdapter(
        ServerCore(), config=AdapterConfig(min_interval=0)
    )
    frame = encode_frame(GetCapabilities())
    original = fragment_frame(frame, "ABC")[0]
    first = type(original)("ABC", 0, 4, original.data, None)
    final = type(original)("ABC", 3, 4, original.data, None)

    assert adapter.receive("EA3AAA", first.body, now=0) == "fragment"
    assert adapter.receive("EA3AAA", final.body, now=1) == "fragment"
    assert adapter.poll(now=2.99) == []
    control = adapter.poll(now=3)

    assert len(control) == 1
    assert control[0].body == "Q1N:ABC:0006"


def test_final_fragment_keeps_short_grace_after_late_fragment() -> None:
    adapter = SelectiveBurstAPRSAdapter(
        ServerCore(), config=AdapterConfig(min_interval=0)
    )
    frame = encode_frame(GetCapabilities())
    original = fragment_frame(frame, "ABC")[0]
    first = type(original)("ABC", 0, 4, original.data, None)
    second = type(original)("ABC", 1, 4, original.data, None)
    final = type(original)("ABC", 3, 4, original.data, None)

    assert adapter.receive("EA3AAA", first.body, now=0) == "fragment"
    assert adapter.receive("EA3AAA", final.body, now=1) == "fragment"
    assert adapter.receive("EA3AAA", second.body, now=1.5) == "fragment"
    assert adapter.poll(now=3.49) == []
    control = adapter.poll(now=3.5)

    assert len(control) == 1
    assert control[0].body == "Q1N:ABC:0004"


def test_proactive_transaction_supersedes_unacked_replaceable_response() -> None:
    adapter = SelectiveBurstAPRSAdapter(
        ServerCore(),
        config=AdapterConfig(ack_timeout=31, max_attempts=5, min_interval=2),
    )
    stale = adapter.queue_frame(
        "EA3AAA",
        encode_frame(GetCapabilities()),
        response_batch=("EA3AAA", "REQ"),
        response_supersedable=True,
    )
    first = adapter.poll(now=0)
    assert first
    assert adapter.pending_count == len(first)

    proactive = adapter.queue_frame(
        "EA3AAA",
        encode_frame(GetCapabilities()),
        proactive=True,
    )

    assert adapter.receive("EA3AAA", encode_burst_ack(stale), now=1) == "ignored"
    assert adapter.poll(now=1) == []
    second = adapter.poll(now=2)

    assert second
    assert {
        parse_fragment(packet.body).transaction_id for packet in second
    } == {proactive}


def test_proactive_transaction_does_not_supersede_nonreplaceable_response() -> None:
    adapter = SelectiveBurstAPRSAdapter(
        ServerCore(),
        config=AdapterConfig(ack_timeout=31, max_attempts=5, min_interval=2),
    )
    protected = adapter.queue_frame(
        "EA3AAA",
        encode_frame(GetCapabilities()),
        response_batch=("EA3AAA", "SEND"),
        response_supersedable=False,
    )
    first = adapter.poll(now=0)
    assert first

    adapter.queue_frame(
        "EA3AAA",
        encode_frame(GetCapabilities()),
        proactive=True,
    )

    assert adapter.poll(now=2) == []
    assert adapter.receive("EA3AAA", encode_burst_ack(protected), now=2) == "acknowledged"
    assert adapter.poll(now=2)
