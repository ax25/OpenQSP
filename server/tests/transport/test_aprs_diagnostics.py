from __future__ import annotations

from openqsp.protocol import End, GetCapabilities, GetNewMessages, Message, Operation, encode_frame
from openqsp.transport.aprs.carriage import APRSFragment, fragment_frame, fragment_frame_v2
from openqsp.transport.aprs.diagnostics import APRSFrameDiagnostics
from openqsp.transport.aprs.selective_burst import encode_burst_ack, encode_missing, encode_stored


def _with_message_id(fragment: APRSFragment, message_id: str) -> str:
    return APRSFragment(
        fragment.transaction_id,
        fragment.index,
        fragment.total,
        fragment.data,
        message_id,
    ).body


def test_single_fragment_request_is_logged_with_cursor_and_max() -> None:
    diagnostics = APRSFrameDiagnostics()
    fragment = fragment_frame(encode_frame(GetNewMessages(since=10, max=20)), "WFH")[0]

    description = diagnostics.describe_received("EA3GNU", fragment.body)

    assert description is not None
    assert "Q1 transaction=WFH fragment=1/1" in description
    assert "GET_NEW_MESSAGES since=10 max=20" in description


def test_q2_single_fragment_is_logged_semantically_without_base91_payload() -> None:
    diagnostics = APRSFrameDiagnostics()
    fragment = fragment_frame_v2(encode_frame(GetCapabilities()), "003")[0]

    description = diagnostics.describe_received("EA3GNU", fragment.body)

    assert description is not None
    assert "Q2 transaction=003 fragment=1/1" in description
    assert "GET_CAPABILITIES" in description
    assert fragment.body not in description


def test_q2_controls_are_human_readable() -> None:
    diagnostics = APRSFrameDiagnostics()

    assert diagnostics.describe_received("EA3GNU", encode_burst_ack("003")) == (
        "A2 transaction=003 ACK"
    )
    assert diagnostics.describe_sent("EA3GNU", encode_stored("003")) == (
        "S2 transaction=003 STORED"
    )
    nack = diagnostics.describe_received("EA3GNU", encode_missing("003", {1, 4}))
    assert nack == "N2 transaction=003 missing=2,5 mask=0x0012"


def test_multifragment_message_is_described_when_complete() -> None:
    diagnostics = APRSFrameDiagnostics()
    fragments = fragment_frame(
        encode_frame(
            Message(
                sequence=7,
                created_at=1788045600,
                author="EA3ABC",
                recipient="EA3GNU",
                body="recibido aprs message 1",
            )
        ),
        "00D",
    )
    assert len(fragments) == 2

    first = diagnostics.describe_sent("EA3GNU", _with_message_id(fragments[0], "0I"))
    second = diagnostics.describe_sent("EA3GNU", _with_message_id(fragments[1], "0J"))

    assert first is not None
    assert "fragment=1/2" in first
    assert "waiting_for_complete_frame" in first
    assert second is not None
    assert "fragment=2/2" in second
    assert "MESSAGE seq=7 from=EA3ABC to=EA3GNU" in second
    assert "body='recibido aprs message 1'" in second


def test_end_and_ack_are_human_readable() -> None:
    diagnostics = APRSFrameDiagnostics()
    fragment = fragment_frame(
        encode_frame(
            End(
                request_operation=Operation.GET_NEW_MESSAGES,
                returned_count=0,
                next_since=10,
                has_more=False,
            )
        ),
        "002",
    )[0]

    end_description = diagnostics.describe_sent(
        "EA3GNU", _with_message_id(fragment, "02")
    )
    ack_description = diagnostics.describe_received("EA3GNU", "ack02")

    assert end_description is not None
    assert (
        "END request=GET_NEW_MESSAGES returned=0 next_since=10 has_more=false"
        in end_description
    )
    assert ack_description == "APRS ACK message_id=02"
