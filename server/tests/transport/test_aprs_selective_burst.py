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

    # The stale response is no longer active, but the normal APRS pacing still
    # applies.  We do not wait for its 31-second ACK timeout.
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
