"""Tests for the transport-independent server-core boundary."""

import pytest

from openqsp.protocol import (
    Ack,
    AckStatus,
    Bulletin,
    BulletinHeader,
    End,
    Error,
    ErrorCode,
    GetBulletin,
    GetNewBulletins,
    Message,
    Operation,
    SendMessage,
    decode_frame,
    encode_frame,
)
from openqsp.server import RequestContext, ServerCore


REQUESTS_WITHOUT_STORES = (
    (GetNewBulletins(0, 5), Operation.GET_NEW_BULLETINS),
    (GetBulletin(1), Operation.GET_BULLETIN),
)


@pytest.mark.parametrize(
    ("protocol_request", "operation"),
    REQUESTS_WITHOUT_STORES,
)
def test_bulletin_requests_without_store_return_busy(
    protocol_request, operation
):
    responses = ServerCore().handle_frame("K1ABC", encode_frame(protocol_request))

    assert len(responses) == 1
    assert isinstance(responses[0], bytes)
    assert decode_frame(responses[0]) == Error(
        operation, ErrorCode.BUSY, "bulletin store unavailable"
    )


def test_authenticated_identity_is_separate_and_reaches_operation_handler():
    class RecordingCore(ServerCore):
        def _handle_send_message(self, context, request):
            seen.append((context, request))
            return [Error(Operation.SEND_MESSAGE, ErrorCode.BUSY, "recorded")]

    seen = []
    request = SendMessage(9, 10, "N0CALL", "payload has no author")
    response = RecordingCore().handle_frame("K1ABC", encode_frame(request))

    assert seen == [(RequestContext("K1ABC"), request)]
    assert not hasattr(request, "author")
    assert decode_frame(response[0]) == Error(
        Operation.SEND_MESSAGE, ErrorCode.BUSY, "recorded"
    )


@pytest.mark.parametrize(
    "response",
    (
        Message(1, 2, 3, "K1ABC", "N0CALL", "body"),
        BulletinHeader(1, 2, 3, "K1ABC", "title"),
        Bulletin(2, 3, "K1ABC", "title", "body"),
        End(Operation.GET_NEW_MESSAGES, 0, 0, False),
        Ack(1, AckStatus.STORED),
        Error(Operation.GET_BULLETIN, ErrorCode.NOT_FOUND, "missing"),
    ),
)
def test_response_only_operations_are_rejected(response):
    result = ServerCore().handle_frame("K1ABC", encode_frame(response))

    assert decode_frame(result[0]) == Error(
        Operation(encode_frame(response)[1]),
        ErrorCode.UNKNOWN_OPERATION,
        "operation is not a client request",
    )


@pytest.mark.parametrize("frame", (b"", b"\x01", b"\x01\x02\x00"))
def test_incomplete_header_is_safely_discarded(frame):
    assert ServerCore().handle_frame("K1ABC", frame) == []


@pytest.mark.parametrize(
    ("frame", "operation", "code"),
    (
        (b"\x01\x02\x00\x09\x00", Operation.GET_NEW_MESSAGES, ErrorCode.INVALID_FRAME),
        (b"\x02\x02\x00\x00", 0, ErrorCode.UNSUPPORTED_VERSION),
        (b"\x01\x7f\x00\x00", 0, ErrorCode.UNKNOWN_OPERATION),
        (
            b"\x01\x04\x01\x08" + b"\x00" * 8,
            Operation.GET_BULLETIN,
            ErrorCode.INVALID_FRAME,
        ),
        (
            b"\x01\x02\x00\x09" + b"\x00" * 9,
            Operation.GET_NEW_MESSAGES,
            ErrorCode.INVALID_FIELD,
        ),
    ),
)
def test_malformed_frames_return_decodable_protocol_errors(frame, operation, code):
    result = ServerCore().handle_frame("K1ABC", frame)

    assert len(result) == 1
    decoded = decode_frame(result[0])
    assert isinstance(decoded, Error)
    assert decoded.request_operation == operation
    assert decoded.error_code == code


def test_malformed_frame_does_not_touch_injected_stores():
    class FailingStore:
        def __getattr__(self, name):
            raise AssertionError(f"storage was accessed: {name}")

    core = ServerCore(message_store=FailingStore(), bulletin_store=FailingStore())

    assert core.handle_frame("K1ABC", b"\x01\x02\x00\x09")
