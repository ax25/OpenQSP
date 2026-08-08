"""Milestone 3.2 tests for SEND_MESSAGE server-core handling."""

from __future__ import annotations

from openqsp.protocol import (
    Stored,
    Error,
    ErrorCode,
    Operation,
    SendMessage,
    decode_frame,
    encode_frame,
)
from openqsp.server import ServerCore
from openqsp.storage import (
    Database,
    MessageStore,
    SequenceExhaustedError,
    StorageIntegrityError,
)


def _database(tmp_path, name="node.db") -> Database:
    database = Database(tmp_path / name)
    database.initialize()
    return database


def _response(core: ServerCore, request: SendMessage, author="K1ABC"):
    frames = core.handle_frame(author, encode_frame(request))
    assert len(frames) == 1
    return decode_frame(frames[0])


def test_valid_message_is_stored_with_authenticated_author(tmp_path):
    database = _database(tmp_path)
    store = MessageStore(database, clock=lambda: 2000)
    core = ServerCore(message_store=store)
    request = SendMessage(1234, "EA3GNU", "hello from RF")

    assert _response(core, request) == Stored()

    page = store.get_new_messages(callsign="EA3GNU", since=0, limit=20)
    assert len(page.messages) == 1
    message = page.messages[0]
    assert message.sequence == 1
    assert message.created_at == request.created_at
    assert message.author == "K1ABC"
    assert message.recipient == request.recipient
    assert message.body == request.body




def test_invalid_object_field_uses_protocol_error():
    frame = bytearray(encode_frame(SendMessage(1234, "EA3GNU", "body")))
    frame[9] = ord("e")  # recipient starts after the fixed fields and length byte

    responses = ServerCore().handle_frame("K1ABC", bytes(frame))

    assert len(responses) == 1
    response = decode_frame(responses[0])
    assert isinstance(response, Error)
    assert response.error_code == ErrorCode.INVALID_FIELD


def test_unrecoverable_sequence_uses_error():
    # A complete frame with only seven payload bytes cannot contain sequence.
    frame = b"\x01\x01\x00\x07" + b"\x01" * 7

    responses = ServerCore().handle_frame("K1ABC", frame)

    assert len(responses) == 1
    response = decode_frame(responses[0])
    assert isinstance(response, Error)
    assert response.request_operation == Operation.SEND_MESSAGE
    assert response.error_code == ErrorCode.INVALID_FIELD


def test_missing_store_returns_busy():
    response = _response(ServerCore(), SendMessage(1234, "EA3GNU", "body"))

    assert response == Error(
        Operation.SEND_MESSAGE, ErrorCode.BUSY, "message store unavailable"
    )


def test_authenticated_callsign_is_validated_without_normalization(tmp_path):
    database = _database(tmp_path)
    core = ServerCore(message_store=MessageStore(database))
    request = SendMessage(1234, "EA3GNU", "body")

    response = _response(core, request, author="k1abc")

    assert response == Error(
        Operation.SEND_MESSAGE,
        ErrorCode.UNAUTHORIZED,
        "invalid authenticated callsign",
    )
    assert MessageStore(database).get_new_messages(
        callsign="EA3GNU", since=0, limit=20
    ).messages == ()


def test_expected_storage_failures_become_protocol_errors():
    class FailingStore:
        def __init__(self, error):
            self.error = error

        def store_message(self, **kwargs):
            raise self.error

    request = SendMessage(1234, "EA3GNU", "body")

    exhausted = _response(
        ServerCore(message_store=FailingStore(SequenceExhaustedError())), request
    )
    corrupt = _response(
        ServerCore(message_store=FailingStore(StorageIntegrityError())), request
    )

    assert exhausted == Error(
        Operation.SEND_MESSAGE, ErrorCode.BUSY, "message storage exhausted"
    )
    assert corrupt == Error(
        Operation.SEND_MESSAGE,
        ErrorCode.INTERNAL_ERROR,
        "message storage integrity failure",
    )
