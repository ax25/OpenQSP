from __future__ import annotations

from pathlib import Path

import pytest
from openqsp.protocol import (
    GetCapabilities,
    GetNewMessages,
    Message,
    SendMessage,
    Stored,
    decode_frame,
    decode_frame_with_flags,
    encode_frame,
)
from openqsp.protocol.constants import UNSOLICITED_FLAG
from openqsp.server import ServerCore
from openqsp.storage import BulletinStore, Database, MessageStore
from openqsp.transport.aprs import AdapterConfig, APRSAdapter
from openqsp.transport.aprs.carriage import APRSFragment, fragment_frame, parse_fragment
from openqsp.transport.aprs.state import Reassembler, ReplayCache, TransactionConflict


class EmptyCore(ServerCore):
    pass


def deliver(
    adapter: APRSAdapter,
    peer: str,
    frame: bytes,
    transaction: str,
    *,
    now: float,
) -> str:
    result = ""
    for number, part in enumerate(fragment_frame(frame, transaction)):
        result = adapter.receive(peer, part.body + f"{{{number:02X}", now=now)
    return result


def test_transaction_allocator_skips_queue_and_pending_ids_at_rollover() -> None:
    adapter = APRSAdapter(
        EmptyCore(), config=AdapterConfig(min_interval=0, transaction_id_space=2)
    )
    assert adapter.queue_frame("EA3AAA", encode_frame(GetCapabilities())) == "000"
    adapter._next_transaction["EA3AAA"] = 0
    assert adapter.queue_frame("EA3AAA", encode_frame(GetCapabilities())) == "001"
    with pytest.raises(OverflowError, match="identifier space exhausted"):
        adapter.queue_frame("EA3AAA", encode_frame(GetCapabilities()))
    assert adapter.queue_frame("EA3BBB", encode_frame(GetCapabilities())) == "000"

    pending_adapter = APRSAdapter(
        EmptyCore(), config=AdapterConfig(min_interval=0, transaction_id_space=2)
    )
    pending_adapter.queue_frame("EA3AAA", encode_frame(GetCapabilities()))
    packet = pending_adapter.poll(now=0)[0]
    assert parse_fragment(packet.body).transaction_id == "000"
    pending_adapter._next_transaction["EA3AAA"] = 0
    assert (
        pending_adapter.queue_frame("EA3AAA", encode_frame(GetCapabilities()))
        == "001"
    )


def test_reassembly_real_reorder_duplicates_conflicts_timeout_and_eviction() -> None:
    frame = encode_frame(SendMessage(1, "EA3BBB", "x" * 208))
    fragments = fragment_frame(frame, "AAA")
    assert len(fragments) > 1
    reassembly = Reassembler(ttl=2, max_entries=2)
    recovered = None
    for fragment in reversed(fragments):
        recovered = reassembly.add("EA3AAA", fragment, 0) or recovered
        if recovered is None:
            assert reassembly.add("EA3AAA", fragment, 0) is None
    assert recovered == frame

    first = fragments[0]
    assert reassembly.add("EA3AAA", first, 0) is None
    with pytest.raises(TransactionConflict, match="conflicting duplicate"):
        reassembly.add(
            "EA3AAA",
            APRSFragment(first.transaction_id, first.index, first.total, "DIFFERENT"),
            0,
        )
    assert reassembly.add("EA3AAA", APRSFragment("AAB", 0, 2, "AQ"), 0) is None
    with pytest.raises(TransactionConflict, match="inconsistent fragment count"):
        reassembly.add("EA3AAA", APRSFragment("AAB", 1, 3, "AA"), 0)

    reassembly.add("EA3AAA", APRSFragment("AAC", 0, 2, "AQ"), 0)
    reassembly.add("EA3AAA", APRSFragment("AAD", 0, 2, "AQ"), 0)
    reassembly.add("EA3AAA", APRSFragment("AAE", 0, 2, "AQ"), 0)
    assert len(reassembly) == 2
    assert ("EA3AAA", "AAC") not in reassembly._entries
    reassembly.expire(2)
    assert len(reassembly) == 0


def test_replay_cache_preserves_order_and_deterministic_bounds() -> None:
    cache = ReplayCache(ttl=2, max_entries=3, max_per_peer=2)
    responses = (b"first", b"second", b"third")
    cache.put("A", "000", b"request", responses, 0)
    replay = cache.get("A", "000", 0)
    assert replay is not None and replay.responses == responses
    cache.put("A", "001", b"one", (), 0)
    cache.put("A", "002", b"two", (), 0)
    assert cache.get("A", "000", 0) is None
    cache.put("B", "000", b"three", (), 0)
    cache.put("C", "000", b"four", (), 0)
    assert len(cache) == 3
    assert cache.get("A", "001", 0) is None
    cache.expire(2)
    assert len(cache) == 0


def test_outbound_queue_bound_and_explicit_priority() -> None:
    adapter = APRSAdapter(
        EmptyCore(), config=AdapterConfig(min_interval=0, queue_capacity=2)
    )
    adapter.queue_frame("EA3AAA", encode_frame(GetCapabilities()), proactive=True)
    explicit = adapter.queue_frame("EA3BBB", encode_frame(GetCapabilities()))
    with pytest.raises(OverflowError, match="queue is full"):
        adapter.queue_frame("EA3CCC", encode_frame(GetCapabilities()))
    first = adapter.poll(now=0)[0]
    assert first.destination == "EA3BBB"
    assert parse_fragment(first.body).transaction_id == explicit


def database_core(path: Path) -> tuple[ServerCore, MessageStore]:
    database = Database(path)
    database.initialize()
    messages = MessageStore(database, clock=lambda: 10)
    return (
        ServerCore(
            message_store=messages,
            bulletin_store=BulletinStore(database, clock=lambda: 10),
        ),
        messages,
    )


def drain_frame(adapter: APRSAdapter, peer: str, now: float) -> bytes | None:
    reassembler = Reassembler()
    for _ in range(32):
        for packet in adapter.poll(now=now):
            if packet.is_ack or packet.destination != peer:
                continue
            fragment = parse_fragment(packet.body)
            adapter.receive(peer, f"ack{fragment.message_id}", now=now)
            frame = reassembler.add("OPENQSP", fragment, now)
            if frame is not None:
                return frame
    return None


def test_proactive_delivery_is_unsolicited_durable_and_reactivates(
    tmp_path: Path,
) -> None:
    now = [0.0]
    core, messages = database_core(tmp_path / "aprs.sqlite")
    adapter = APRSAdapter(
        core,
        config=AdapterConfig(
            min_interval=0,
            ack_timeout=1,
            max_attempts=2,
            activity_timeout=10,
        ),
        clock=lambda: now[0],
    )
    recipient = "EA3BBB-10"
    assert (
        deliver(
            adapter,
            recipient,
            encode_frame(GetCapabilities()),
            "100",
            now=now[0],
        )
        == "completed"
    )
    assert drain_frame(adapter, recipient, now[0]) is not None

    send = encode_frame(SendMessage(1, "EA3BBB", "durable proactive mail"))
    assert deliver(adapter, "EA3AAA-7", send, "101", now=now[0]) == "completed"
    stored = drain_frame(adapter, "EA3AAA-7", now[0])
    assert stored is not None and isinstance(decode_frame(stored), Stored)
    pushed = drain_frame(adapter, recipient, now[0])
    assert pushed is not None
    message, flags = decode_frame_with_flags(pushed)
    assert isinstance(message, Message) and message.body == "durable proactive mail"
    assert flags == UNSOLICITED_FLAG

    # Deliberately fail the next push; durable storage remains authoritative.
    second = encode_frame(SendMessage(2, "EA3BBB", "push may fail"))
    assert deliver(adapter, "EA3AAA-7", second, "102", now=now[0]) == "completed"
    assert drain_frame(adapter, "EA3AAA-7", now[0]) is not None
    adapter.poll(now=0)
    adapter.poll(now=1)
    adapter.poll(now=2)
    assert adapter.failed_packets
    page = messages.get_new_messages(callsign="EA3BBB", since=0, limit=20)
    assert [item.body for item in page.messages] == [
        "durable proactive mail",
        "push may fail",
    ]

    now[0] = 11
    inactive = encode_frame(SendMessage(3, "EA3BBB", "inactive"))
    assert deliver(adapter, "EA3AAA-7", inactive, "103", now=11) == "completed"
    assert not any(item.peer == recipient for item in adapter._queue)
    assert (
        deliver(
            adapter,
            recipient,
            encode_frame(GetNewMessages(0, 20)),
            "104",
            now=11,
        )
        == "completed"
    )
    assert adapter.is_active(recipient, now=11)
    retrieved = []
    for _ in range(4):
        frame = drain_frame(adapter, recipient, now[0])
        if frame is not None:
            retrieved.append(decode_frame(frame))
    assert any(
        isinstance(item, Message) and item.body == "push may fail"
        for item in retrieved
    )


def test_connection_loss_clears_link_delivery_but_preserves_durable_and_ttl_state(
    tmp_path: Path,
) -> None:
    core, messages = database_core(tmp_path / "loss.sqlite")
    adapter = APRSAdapter(core, config=AdapterConfig(min_interval=0))
    request = encode_frame(SendMessage(1, "EA3BBB", "survives reconnect"))
    assert deliver(adapter, "EA3AAA-7", request, "200", now=0) == "completed"
    partial = APRSFragment("201", 0, 2, "AQ", "55")
    assert adapter.receive("EA3BBB-10", partial.body, now=0) == "fragment"
    assert adapter.queued_count > 0
    assert len(adapter.replay) == 1 and len(adapter.reassembly) == 1

    adapter.connection_lost()
    assert adapter.queued_count == adapter.pending_count == 0
    assert adapter.poll(now=0) == []
    assert len(adapter.replay) == 1 and len(adapter.reassembly) == 1
    page = messages.get_new_messages(callsign="EA3BBB", since=0, limit=20)
    assert [item.body for item in page.messages] == ["survives reconnect"]
