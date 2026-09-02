from __future__ import annotations

from openqsp.protocol import (
    GetCapabilities,
    GetNewMessages,
    Message,
    SendMessage,
    Stored,
    decode_frame,
    encode_frame,
)
from openqsp.server import ServerCore
from openqsp.storage import Database, MessageStore
from openqsp.transport.aprs import AdapterConfig, APRSAdapter
from openqsp.transport.aprs.carriage import (
    decode_frame_text,
    fragment_frame,
    parse_fragment,
)


def _core_with_store(tmp_path) -> ServerCore:
    database = Database(tmp_path / "node.db")
    database.initialize()
    return ServerCore(message_store=MessageStore(database))


def _deliver(
    adapter: APRSAdapter,
    peer: str,
    frame: bytes,
    transaction: str,
    *,
    now: float,
    message_ids: list[str] | None = None,
) -> str:
    result = ""
    parts = fragment_frame(frame, transaction)
    if message_ids is not None:
        assert len(message_ids) == len(parts)
    for index, part in enumerate(parts):
        body = part.body
        if message_ids is not None:
            body = f"{body}{{{message_ids[index]}"
        result = adapter.receive(peer, body, now=now + index * 0.01)
    return result


def _decode_packet_body(body: str):
    fragment = parse_fragment(body)
    assert fragment.total == 1
    return decode_frame(decode_frame_text(fragment.data))


def test_opted_in_send_uses_commit_ack_without_stored_frame(tmp_path) -> None:
    adapter = APRSAdapter(
        _core_with_store(tmp_path), config=AdapterConfig(min_interval=0)
    )
    peer = "EA3GNU"
    request = encode_frame(SendMessage(1_788_097_704, "EA3EFG", "message A"))
    parts = fragment_frame(request, "S0A")
    ids = [f"C{index:02d}" for index in range(len(parts))]

    assert _deliver(adapter, peer, request, "S0A", now=0, message_ids=ids) == "completed"

    confirmations = adapter.poll(now=1)
    assert [packet.body for packet in confirmations] == [f"ack{value}" for value in ids]
    assert adapter.queued_count == 0
    assert adapter.pending_count == 0


def test_replayed_opted_in_send_gets_commit_ack_without_reexecution(tmp_path) -> None:
    core = _core_with_store(tmp_path)
    adapter = APRSAdapter(core, config=AdapterConfig(min_interval=0))
    peer = "EA3GNU"
    request = encode_frame(SendMessage(1_788_097_704, "EA3EFG", "message A"))
    parts = fragment_frame(request, "S0A")
    first_ids = [f"C{index:02d}" for index in range(len(parts))]
    replay_ids = [f"CR{index}" for index in range(len(parts))]

    assert _deliver(adapter, peer, request, "S0A", now=0, message_ids=first_ids) == "completed"
    assert [packet.body for packet in adapter.poll(now=1)] == [
        f"ack{value}" for value in first_ids
    ]

    assert _deliver(adapter, peer, request, "S0A", now=2, message_ids=replay_ids) == "replayed"
    assert [packet.body for packet in adapter.poll(now=3)] == [
        f"ack{value}" for value in replay_ids
    ]
    assert adapter.queued_count == 0
    assert adapter.pending_count == 0


def test_opted_in_send_failure_returns_rej_without_error_frame() -> None:
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    peer = "EA3GNU"
    request = encode_frame(SendMessage(1_788_097_704, "EA3EFG", "no store"))
    parts = fragment_frame(request, "BAD")
    ids = [f"C{index:02d}" for index in range(len(parts))]

    assert _deliver(adapter, peer, request, "BAD", now=0, message_ids=ids) == "completed"
    assert [packet.body for packet in adapter.poll(now=1)] == [f"rej{ids[-1]}"]
    assert adapter.queued_count == 0


def test_legacy_send_with_normal_aprs_id_keeps_ack_and_stored(tmp_path) -> None:
    adapter = APRSAdapter(
        _core_with_store(tmp_path), config=AdapterConfig(min_interval=0)
    )
    peer = "EA3GNU"
    request = encode_frame(SendMessage(1_788_097_704, "EA3EFG", "legacy"))
    parts = fragment_frame(request, "LEG")
    ids = [f"L{index}" for index in range(len(parts))]

    assert _deliver(adapter, peer, request, "LEG", now=0, message_ids=ids) == "completed"
    response = adapter.poll(now=1)
    assert response[0].body == f"ack{ids[-1]}"
    stored_packets = [packet for packet in response if not packet.is_ack]
    assert len(stored_packets) == 1
    assert isinstance(_decode_packet_body(stored_packets[0].body), Stored)


def test_send_without_aprs_message_id_keeps_legacy_stored_response(tmp_path) -> None:
    adapter = APRSAdapter(
        _core_with_store(tmp_path), config=AdapterConfig(min_interval=0)
    )
    peer = "EA3GNU"

    assert (
        _deliver(
            adapter,
            peer,
            encode_frame(SendMessage(1_788_097_704, "EA3EFG", "legacy no id")),
            "LG2",
            now=0,
        )
        == "completed"
    )
    response = adapter.poll(now=0)
    assert len(response) == 1
    assert isinstance(_decode_packet_body(response[0].body), Stored)


def test_new_commit_send_supersedes_unacked_older_replaceable_response(tmp_path) -> None:
    adapter = APRSAdapter(
        _core_with_store(tmp_path),
        config=AdapterConfig(min_interval=0, ack_timeout=31, max_attempts=5),
    )
    peer = "EA3GNU"

    assert (
        _deliver(
            adapter,
            peer,
            encode_frame(GetCapabilities()),
            "OLD",
            now=0,
        )
        == "completed"
    )
    old_response = adapter.poll(now=0)
    assert len(old_response) == 1
    assert adapter.pending_count == 1

    request = encode_frame(SendMessage(1_788_097_704, "EA3EFG", "test 5"))
    ids = [f"C{index:02d}" for index in range(len(fragment_frame(request, "NEW")))]
    assert _deliver(adapter, peer, request, "NEW", now=1, message_ids=ids) == "completed"

    # The old replaceable capabilities response is discarded. The new
    # SEND_MESSAGE only needs its commit ACK(s), with no STORED response queued.
    assert adapter.pending_count == 0
    assert adapter.queued_count == 0
    confirmations = adapter.poll(now=2)
    assert [packet.body for packet in confirmations] == [
        f"ack{value}" for value in ids
    ]
    assert old_response[0].body not in {packet.body for packet in confirmations}


def test_new_request_does_not_supersede_proactive_delivery() -> None:
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    peer = "EA3GNU"

    adapter.queue_frame(peer, encode_frame(GetCapabilities()), proactive=True)
    proactive = adapter.poll(now=0)
    assert len(proactive) == 1
    assert adapter.pending_count == 1

    assert (
        _deliver(
            adapter,
            peer,
            encode_frame(GetCapabilities()),
            "NEW",
            now=1,
        )
        == "completed"
    )
    assert adapter.pending_count == 1
    assert adapter.poll(now=1) == []


def test_message_cursor_supersedes_unacked_delivery_it_already_covers(tmp_path) -> None:
    database = Database(tmp_path / "node.db")
    database.initialize()
    store = MessageStore(database)
    core = ServerCore(message_store=store)
    adapter = APRSAdapter(
        core,
        config=AdapterConfig(min_interval=0, ack_timeout=31, max_attempts=5),
    )
    peer = "EA3GNU"
    sequence = store.store_message(
        created_at=1_788_097_704,
        author="EA3EFG",
        recipient=peer,
        body="already received despite lost APRS ACK",
    )
    message = Message(
        sequence,
        1_788_097_704,
        "EA3EFG",
        peer,
        "already received despite lost APRS ACK",
    )

    assert adapter.deliver_message(message, peer)
    first_delivery = adapter.poll(now=0)
    assert len(first_delivery) == 1
    assert adapter.pending_count == 1

    # The client reconnects after receiving the message but losing its ACK.
    # Its cursor is stronger evidence than the stale pending transport ACK.
    request = encode_frame(GetNewMessages(sequence, 20))
    assert _deliver(adapter, peer, request, "NEW", now=1) == "completed"

    assert adapter.pending_count == 0
    assert store.message_state(store.get_message(recipient=peer, sequence=sequence))[0] == "delivered"

    response = adapter.poll(now=1)
    assert len(response) == 1
    assert first_delivery[0].body not in {packet.body for packet in response}
