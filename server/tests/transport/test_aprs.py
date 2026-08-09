from __future__ import annotations

import pytest

from openqsp.protocol import GetCapabilities, GetNewMessages, encode_frame
from openqsp.server import ServerCore
from openqsp.transport.aprs import APRSAdapter, AdapterConfig, OutboundPacket
from openqsp.transport.aprs.aprsis import (
    APRSISConfig,
    format_packet,
    login_line,
    parse_logresp,
    parse_packet,
)
from openqsp.transport.aprs.carriage import (
    APRSFragment,
    CarriageError,
    decode_frame_text,
    encode_frame_text,
    fragment_frame,
    parse_fragment,
)
from openqsp.transport.aprs.state import Reassembler, ReplayCache, TransactionConflict


def test_carriage_round_trip_and_canonical_syntax() -> None:
    frame = encode_frame(GetCapabilities())
    text = encode_frame_text(frame)
    assert "=" not in text
    fragments = fragment_frame(frame, "0A7")
    assert decode_frame_text("".join(part.data for part in fragments)) == frame
    parsed = parse_fragment(fragments[0].body + "{4F")
    assert parsed == APRSFragment("0A7", 0, 1, text, "4F")


@pytest.mark.parametrize("body", ["Q1:aaa:00/01:AQ", "Q1:000:01/01:AQ", "Q1:000:00/00:AQ", "Q1:000:00/01:A="])
def test_carriage_rejects_noncanonical_fragments(body: str) -> None:
    with pytest.raises(CarriageError):
        parse_fragment(body)


def test_reassembly_reorders_duplicates_conflicts_and_expires() -> None:
    frame = encode_frame(GetCapabilities())
    original = fragment_frame(frame, "001")[0]
    reassembly = Reassembler(ttl=2, max_entries=1)
    assert reassembly.add("EA3AAA", original, 0) == frame
    split = APRSFragment("002", 0, 2, "AQ")
    assert reassembly.add("EA3AAA", split, 0) is None
    assert reassembly.add("EA3AAA", split, 1) is None
    with pytest.raises(TransactionConflict):
        reassembly.add("EA3AAA", APRSFragment("002", 0, 2, "Ag"), 1)
    reassembly.add("EA3AAA", APRSFragment("003", 0, 2, "AQ"), 1)
    reassembly.expire(3)
    assert len(reassembly) == 0


def test_replay_cache_is_peer_and_globally_bounded() -> None:
    cache = ReplayCache(ttl=2, max_entries=2, max_per_peer=1)
    cache.put("A", "000", b"a", (), 0)
    cache.put("A", "001", b"b", (), 0)
    assert cache.get("A", "000", 0) is None
    cache.put("B", "000", b"c", (), 0)
    assert len(cache) == 2
    cache.expire(2)
    assert len(cache) == 0


class CountingCore(ServerCore):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def handle_frame(self, authenticated_callsign: str, frame_bytes: bytes) -> list[bytes]:
        self.calls += 1
        return super().handle_frame(authenticated_callsign, frame_bytes)


def deliver(adapter: APRSAdapter, peer: str, frame: bytes, transaction: str, now: float = 0) -> str:
    result = ""
    for number, part in enumerate(fragment_frame(frame, transaction)):
        result = adapter.receive(peer, part.body + f"{{{number:02X}", now=now)
    return result


def test_adapter_acks_replays_and_rejects_conflict() -> None:
    core = CountingCore()
    adapter = APRSAdapter(core, config=AdapterConfig(min_interval=0))
    frame = encode_frame(GetCapabilities())
    assert deliver(adapter, "EA3AAA-10", frame, "ABC") == "completed"
    assert core.calls == 1 and adapter.is_active("EA3AAA-10", now=0)
    assert deliver(adapter, "EA3AAA-10", frame, "ABC") == "replayed"
    assert core.calls == 1
    other = encode_frame(GetNewMessages(0, 1))
    assert deliver(adapter, "EA3AAA-10", other, "ABC") == "conflict"
    assert core.calls == 1
    packets = adapter.poll(now=0)
    assert any(packet.body.startswith("ack") for packet in packets)


def test_retry_reuses_message_id_and_wrong_peer_ack_is_ignored() -> None:
    adapter = APRSAdapter(CountingCore(), config=AdapterConfig(ack_timeout=1, max_attempts=2, min_interval=0))
    adapter.queue_frame("EA3AAA", encode_frame(GetCapabilities()))
    first = adapter.poll(now=0)[0]
    assert adapter.receive("EA3BBB", "ack00", now=0) == "ignored"
    retry = adapter.poll(now=1)[0]
    assert retry.body == first.body
    adapter.poll(now=2)
    assert adapter.pending_count == 0 and adapter.failed_packets == [first]


def test_aprsis_lines() -> None:
    config = APRSISConfig(passcode="external")
    assert login_line(config).endswith("filter g/OPENQSP")
    assert parse_logresp("# logresp OPENQSP verified, server T2TEST") is True
    assert parse_logresp("# logresp OPENQSP unverified") is False
    line = "EA3AAA>APRS,TCPIP*::OPENQSP  :Q1:000:00/01:AQ{01"
    assert parse_packet(line) == ("EA3AAA", "OPENQSP", "Q1:000:00/01:AQ{01")
    packet = OutboundPacket("OPENQSP", "EA3AAA", "ack01", True)
    assert format_packet(packet) == "OPENQSP>APOQSP,TCPIP*::EA3AAA   :ack01"
