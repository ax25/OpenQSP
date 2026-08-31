from __future__ import annotations

from openqsp.server import ServerCore
from openqsp.transport.aprs import AdapterConfig, APRSAdapter
from openqsp.transport.aprs.carriage import parse_fragment


def test_transaction_fragments_are_sent_in_one_burst() -> None:
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    adapter.queue_frame("EA3AAA", b"x" * 180)

    packets = adapter.poll(now=0)

    assert len(packets) > 1
    fragments = [parse_fragment(packet.body) for packet in packets]
    assert [fragment.index for fragment in fragments] == list(range(len(fragments)))
    assert {fragment.transaction_id for fragment in fragments} == {
        fragments[0].transaction_id
    }
    assert adapter.pending_count == len(fragments)
    assert adapter.queued_count == 0


def test_retry_burst_contains_only_unacknowledged_fragments() -> None:
    adapter = APRSAdapter(
        ServerCore(),
        config=AdapterConfig(ack_timeout=1, max_attempts=3, min_interval=0),
    )
    adapter.queue_frame("EA3AAA", b"x" * 180)
    first_burst = adapter.poll(now=0)
    fragments = [parse_fragment(packet.body) for packet in first_burst]
    assert len(fragments) > 2

    missing = fragments[1].message_id
    assert missing is not None
    for fragment in fragments:
        if fragment.message_id == missing:
            continue
        assert fragment.message_id is not None
        assert adapter.receive("EA3AAA", f"ack{fragment.message_id}", now=0) == "acknowledged"

    assert adapter.pending_count == 1

    retry = adapter.poll(now=1)

    assert len(retry) == 1
    assert parse_fragment(retry[0].body).message_id == missing


def test_next_transaction_waits_for_previous_transaction_acks() -> None:
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    first_transaction = adapter.queue_frame("EA3AAA", b"x" * 180)
    second_transaction = adapter.queue_frame("EA3AAA", b"y" * 180)

    first_burst = adapter.poll(now=0)
    assert {
        parse_fragment(packet.body).transaction_id for packet in first_burst
    } == {first_transaction}
    assert adapter.queued_count > 0

    for packet in first_burst:
        message_id = parse_fragment(packet.body).message_id
        assert message_id is not None
        assert adapter.receive("EA3AAA", f"ack{message_id}", now=0) == "acknowledged"

    second_burst = adapter.poll(now=0)
    assert {
        parse_fragment(packet.body).transaction_id for packet in second_burst
    } == {second_transaction}
