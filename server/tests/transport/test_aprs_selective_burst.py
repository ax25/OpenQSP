from __future__ import annotations

from openqsp.protocol import GetCapabilities, SendMessage, encode_frame
from openqsp.server import ServerCore
from openqsp.transport.aprs import (
    AdapterConfig,
    SelectiveBurstAPRSAdapter,
    encode_burst_ack,
    encode_missing,
    parse_burst_control,
)
from openqsp.transport.aprs.carriage import (
    APRSFragment,
    base91_encode,
    fragment_frame_v2,
    parse_fragment,
)


def _partial(transaction: str, index: int, total: int, raw: bytes) -> APRSFragment:
    return APRSFragment(
        transaction,
        index,
        total,
        base91_encode(raw),
        version=2,
        raw_data=raw,
    )


def test_burst_control_round_trip() -> None:
    transaction = "05Z"
    ack = encode_burst_ack(transaction)
    assert ack.startswith("A2")
    assert len(ack) <= 4
    assert parse_burst_control(ack) == (
        "ack",
        transaction,
        frozenset(),
    )
    body = encode_missing(transaction, {1, 4, 15})
    assert body.startswith("N2")
    assert len(body) <= 6
    assert parse_burst_control(body) == (
        "missing",
        transaction,
        frozenset({1, 4, 15}),
    )


def test_legacy_q1_burst_controls_remain_parseable() -> None:
    assert parse_burst_control("Q1A:0A7") == ("ack", "0A7", frozenset())
    assert parse_burst_control("Q1N:0A7:8012") == (
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
    assert all(packet.body.startswith("Q2") for packet in burst)
    assert all("{" not in packet.body for packet in burst)
    assert all(parse_fragment(packet.body).message_id is None for packet in burst)
    assert adapter.pending_count == len(burst)
    assert adapter.receive("EA3AAA", encode_burst_ack(transaction), now=0) == "acknowledged"
    assert adapter.pending_count == 0


def test_complete_inbound_q2_transaction_emits_a2_for_same_transaction() -> None:
    adapter = SelectiveBurstAPRSAdapter(
        ServerCore(), config=AdapterConfig(min_interval=0)
    )
    transaction = "00A"
    fragments = fragment_frame_v2(encode_frame(GetCapabilities()), transaction)

    for fragment in fragments[:-1]:
        assert adapter.receive("EA3AAA", fragment.body, now=0) == "fragment"
    assert adapter.receive("EA3AAA", fragments[-1].body, now=0) == "completed"

    outbound = adapter.poll(now=0)
    assert outbound
    assert parse_burst_control(outbound[0].body) == (
        "ack",
        transaction,
        frozenset(),
    )


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


def test_selective_repair_retries_only_requested_fragments_after_ack_timeout() -> None:
    adapter = SelectiveBurstAPRSAdapter(
        ServerCore(),
        config=AdapterConfig(ack_timeout=31, max_attempts=4, min_interval=0),
    )
    frame = encode_frame(
        SendMessage(
            created_at=1_700_000_000,
            recipient="EA3BBB",
            body="x" * 180,
        )
    )
    transaction = adapter.queue_frame("EA3AAA", frame)
    first = adapter.poll(now=0)
    assert len(first) > 1

    assert adapter.receive("EA3AAA", encode_missing(transaction, {0}), now=1) == (
        "repair-requested"
    )
    repair = adapter.poll(now=1)
    assert len(repair) == 1
    assert parse_fragment(repair[0].body).index == 0

    # If the final A2 is lost, never fall back to the complete burst: retry
    # only the repair subset so a completed receiver can answer A2 again.
    timeout_repair = adapter.poll(now=32)
    assert len(timeout_repair) == 1
    assert parse_fragment(timeout_repair[0].body).index == 0

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
    raw = encode_frame(GetCapabilities())
    first = _partial("05Z", 0, 2, raw)

    assert adapter.receive("EA3AAA", first.body, now=0) == "fragment"
    assert adapter.poll(now=0) == []
    control = adapter.poll(now=1)

    assert len(control) == 1
    assert parse_burst_control(control[0].body) == (
        "missing",
        "05Z",
        frozenset({1}),
    )
    assert control[0].body.startswith("N2")


def test_default_repair_grace_waits_five_seconds_after_latest_nonfinal_fragment() -> None:
    adapter = SelectiveBurstAPRSAdapter(
        ServerCore(), config=AdapterConfig(min_interval=0)
    )
    raw = encode_frame(GetCapabilities())
    first = _partial("05Z", 0, 4, raw)
    second = _partial("05Z", 1, 4, raw)

    assert adapter.receive("EA3AAA", first.body, now=0) == "fragment"
    assert adapter.poll(now=4.99) == []
    assert adapter.receive("EA3AAA", second.body, now=4.99) == "fragment"
    assert adapter.poll(now=9.98) == []

    control = adapter.poll(now=9.99)
    assert len(control) == 1
    assert parse_burst_control(control[0].body) == (
        "missing",
        "05Z",
        frozenset({2, 3}),
    )


def test_final_fragment_shortens_missing_repair_grace_to_two_seconds() -> None:
    adapter = SelectiveBurstAPRSAdapter(
        ServerCore(), config=AdapterConfig(min_interval=0)
    )
    raw = encode_frame(GetCapabilities())
    first = _partial("05Z", 0, 4, raw)
    final = _partial("05Z", 3, 4, raw)

    assert adapter.receive("EA3AAA", first.body, now=0) == "fragment"
    assert adapter.receive("EA3AAA", final.body, now=1) == "fragment"
    assert adapter.poll(now=2.99) == []
    control = adapter.poll(now=3)

    assert len(control) == 1
    assert parse_burst_control(control[0].body) == (
        "missing",
        "05Z",
        frozenset({1, 2}),
    )


def test_final_fragment_keeps_short_grace_after_late_fragment() -> None:
    adapter = SelectiveBurstAPRSAdapter(
        ServerCore(), config=AdapterConfig(min_interval=0)
    )
    raw = encode_frame(GetCapabilities())
    first = _partial("05Z", 0, 4, raw)
    second = _partial("05Z", 1, 4, raw)
    final = _partial("05Z", 3, 4, raw)

    assert adapter.receive("EA3AAA", first.body, now=0) == "fragment"
    assert adapter.receive("EA3AAA", final.body, now=1) == "fragment"
    assert adapter.receive("EA3AAA", second.body, now=1.5) == "fragment"
    assert adapter.poll(now=3.49) == []
    control = adapter.poll(now=3.5)

    assert len(control) == 1
    assert parse_burst_control(control[0].body) == (
        "missing",
        "05Z",
        frozenset({2}),
    )


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
