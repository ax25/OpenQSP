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
) -> str:
    result = ""
    for part in fragment_frame(frame, transaction):
        result = adapter.receive(peer, part.body, now=now)
    return result


def _decode_packet_body(body: str):
    fragment = parse_fragment(body)
    assert fragment.total == 1
    return decode_frame(decode_frame_text(fragment.data))


def test_new_request_supersedes_unacked_older_response() -> None:
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

    assert (
        _deliver(
            adapter,
            peer,
            encode_frame(SendMessage(1_788_097_704, "EA3EFG", "test 5")),
            "NEW",
            now=1,
        )
        == "completed"
    )

    # Replaceable responses such as capabilities may still be superseded by a
    # newer valid request instead of blocking the peer for the full retry window.
    assert adapter.pending_count == 0
    new_response = adapter.poll(now=1)
    assert len(new_response) == 1
    assert isinstance(_decode_packet_body(new_response[0].body), Stored)
    assert new_response[0].body != old_response[0].body


def test_new_send_preserves_unacked_older_stored_confirmation() -> None:
    adapter = APRSAdapter(
        ServerCore(),
        config=AdapterConfig(min_interval=0, ack_timeout=31, max_attempts=5),
    )
    peer = "EA3GNU"

    assert (
        _deliver(
            adapter,
            peer,
            encode_frame(SendMessage(1_788_097_704, "EA3EFG", "message A")),
            "S0A",
            now=0,
        )
        == "completed"
    )
    first_response = adapter.poll(now=0)
    assert len(first_response) == 1
    assert isinstance(_decode_packet_body(first_response[0].body), Stored)
    first_message_id = parse_fragment(first_response[0].body).message_id
    assert first_message_id is not None
    assert adapter.pending_count == 1

    assert (
        _deliver(
            adapter,
            peer,
            encode_frame(SendMessage(1_788_097_705, "EA3EFG", "message B")),
            "S0B",
            now=1,
        )
        == "completed"
    )

    # STORED A is a durable-operation confirmation and must not be discarded
    # merely because SEND B arrived. B waits behind A in the per-peer APRS
    # response queue, preserving unambiguous FIFO confirmation semantics.
    assert adapter.pending_count == 1
    assert adapter.queued_count == 1
    assert adapter.poll(now=1) == []

    assert adapter.receive(peer, f"ack{first_message_id}", now=2) == "acknowledged"
    assert adapter.pending_count == 0

    second_response = adapter.poll(now=2)
    assert len(second_response) == 1
    assert isinstance(_decode_packet_body(second_response[0].body), Stored)
    assert second_response[0].body != first_response[0].body


def test_new_request_does_not_supersede_proactive_delivery() -> None:
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    peer = "EA3GNU"

    # Proactive work has no request response_batch and must retain its normal
    # APRS ACK/retry semantics when the peer sends a newer request.
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
