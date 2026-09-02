from __future__ import annotations

from openqsp.protocol import SendMessage, encode_frame
from openqsp.transport.aprs.carriage import (
    MAX_APRS_BODY,
    base91_decode,
    base91_encode,
    fragment_frame_v2,
    parse_fragment,
)
from openqsp.transport.aprs.state import Reassembler


def test_base91_round_trip_all_byte_values() -> None:
    raw = bytes(range(256))
    encoded = base91_encode(raw)

    assert "{" not in encoded
    assert "|" not in encoded
    assert "~" not in encoded
    assert base91_decode(encoded) == raw


def test_q2_fragment_round_trip() -> None:
    frame = encode_frame(
        SendMessage(
            created_at=1_700_000_000,
            recipient="EA3BBB",
            body="hello from q2",
        )
    )
    fragments = fragment_frame_v2(frame, "005")

    assert fragments
    for expected, fragment in enumerate(fragments):
        assert fragment.body.startswith("Q2")
        assert "{" not in fragment.body
        assert len(fragment.body) <= MAX_APRS_BODY
        decoded = parse_fragment(fragment.body)
        assert decoded.version == 2
        assert decoded.transaction_id == "005"
        assert decoded.index == expected
        assert decoded.total == len(fragments)
        assert decoded.raw_data == fragment.raw_data


def test_q2_reassembles_raw_core_frame() -> None:
    frame = encode_frame(
        SendMessage(
            created_at=1_700_000_000,
            recipient="EA3BBB",
            body="x" * 208,
        )
    )
    fragments = fragment_frame_v2(frame, "00A")
    reassembler = Reassembler()

    completed = None
    for fragment in reversed(fragments):
        completed = reassembler.add("EA3AAA", parse_fragment(fragment.body), 0)

    assert completed == frame


def test_q2_reduces_max_send_message_to_five_fragments() -> None:
    frame = encode_frame(
        SendMessage(
            created_at=1_700_000_000,
            recipient="EA3BBB",
            body="x" * 208,
        )
    )

    fragments = fragment_frame_v2(frame, "00B")

    assert len(frame) == 224
    assert len(fragments) == 5
    assert all(len(fragment.body) <= MAX_APRS_BODY for fragment in fragments)
