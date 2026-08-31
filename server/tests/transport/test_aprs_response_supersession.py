from __future__ import annotations

from openqsp.protocol import (
    GetCapabilities,
    SendMessage,
    Stored,
    decode_frame,
    encode_frame,
)
from openqsp.server import ServerCore
from openqsp.transport.aprs import AdapterConfig, APRSAdapter
from openqsp.transport.aprs.carriage import (
    decode_frame_text,
    fragment_frame,
    parse_fragment,
)


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


def test_send_message_with_aprs_id_uses_commit_ack_without_stored_frame() -> None:
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    peer = "EA3GNU"
    request = encode_frame(SendMessage(1_788_097_704, "EA3EFG", "message A"))
    parts = fragment_frame(request, "S0A")
    ids = [f"{index:02d}" for index in range(len(parts))]

    assert _deliver(adapter, peer, request, "S0A", now=0, message_ids=ids) == "completed"

    confirmations = adapter.poll(now=1)
    assert [packet.body for packet in confirmations] == [f"ack{value}" for value in ids]
    assert adapter.queued_count == 0
    assert adapter.pending_count == 0


def test_replayed_send_message_gets_new_commit_ack_without_reexecution_response() -> None:
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    peer = "EA3GNU"
    request = encode_frame(SendMessage(1_788_097_704, "EA3EFG", "message A"))
    parts = fragment_frame(request, "S0A")
    first_ids = [f"{index:02d}" for index in range(len(parts))]
    replay_ids = [f"R{index}" for index in range(len(parts))]

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


def test_send_without_aprs_message_id_keeps_legacy_stored_response() -> None:
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    peer = "EA3GNU"

    assert (
        _deliver(
            adapter,
            peer,
            encode_frame(SendMessage(1_788_097_704, "EA3EFG", "legacy")),
            "LEG",
            now=0,
        )
        == "completed"
    )
    response = adapter.poll(now=0)
    assert len(response) == 1
    assert isinstance(_decode_packet_body(response[0].body), Stored)


def test_new_request_supersedes_unacked_older_replaceable_response() -> None:
    adapter = APRSAdapter(
        ServerCore(),
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
    ids = [f"N{index}" for index in range(len(fragment_frame(request, "NEW")))]
    assert _deliver(adapter, peer, request, "NEW", now=1, message_ids=ids) == "completed"

    # The old replaceable capabilities response is discarded and SEND_MESSAGE
    # needs only its commit ACK(s), with no STORED response queued behind it.
    assert adapter.pending_count == 0
    assert adapter.queued_count == 0
    assert [packet.body for packet in adapter.poll(now=2)] == [
        f"ack{value}" for value in ids
    ]
    assert old_response[0].body not in {packet.body for packet in adapter.poll(now=3)}


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
