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

    # Receiving a newer valid request proves the peer is active. Its response
    # supersedes the older request/response batch instead of waiting up to the
    # full retry window for the old APRS ACK.
    assert adapter.pending_count == 0
    new_response = adapter.poll(now=1)
    assert len(new_response) == 1
    assert isinstance(_decode_packet_body(new_response[0].body), Stored)
    assert new_response[0].body != old_response[0].body


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
