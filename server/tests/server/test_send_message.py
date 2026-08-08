"""Milestone 3.2 tests for SEND_MESSAGE server-core handling."""

from __future__ import annotations

from openqsp.protocol import (
    Ack,
    AckStatus,
    Error,
    ErrorCode,
    Operation,
    SendMessage,
    decode_frame,
    encode_frame,
)
from openqsp.server import ServerCore
from openqsp.storage import (
    BulletinStore,
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
    request = SendMessage(101, 1234, "EA3GNU", "hello from RF")

    assert _response(core, request) == Ack(101, AckStatus.STORED)

    page = store.get_new_messages(callsign="EA3GNU", since=0, limit=20)
    assert len(page.messages) == 1
    message = page.messages[0]
    assert message.message_id == request.message_id
    assert message.created_at == request.created_at
    assert message.author == "K1ABC"
    assert message.recipient == request.recipient
    assert message.body == request.body


def test_identical_retry_and_conflict_preserve_original(tmp_path):
    database = _database(tmp_path)
    store = MessageStore(database)
    core = ServerCore(message_store=store)
    original = SendMessage(102, 1234, "EA3GNU", "original")

    assert _response(core, original) == Ack(102, AckStatus.STORED)
    assert _response(core, original) == Ack(102, AckStatus.ALREADY_STORED)
    changed = SendMessage(102, 1234, "EA3GNU", "changed")
    assert _response(core, changed) == Ack(102, AckStatus.CONFLICT)

    messages = store.get_new_messages(callsign="EA3GNU", since=0, limit=20).messages
    assert len(messages) == 1
    assert messages[0].body == "original"


def test_bulletin_identifier_is_cross_type_conflict(tmp_path):
    database = _database(tmp_path)
    BulletinStore(database).store_bulletin(
        bulletin_id=103,
        created_at=1000,
        author="N0CALL",
        title="notice",
        body="bulletin body",
    )

    response = _response(
        ServerCore(message_store=MessageStore(database)),
        SendMessage(103, 1234, "EA3GNU", "private body"),
    )

    assert response == Ack(103, AckStatus.CONFLICT)
    assert MessageStore(database).get_new_messages(
        callsign="EA3GNU", since=0, limit=20
    ).messages == ()


def test_retry_after_database_restart_is_already_stored(tmp_path):
    request = SendMessage(104, 1234, "EA3GNU", "durable")
    first_database = _database(tmp_path, "restart.db")
    assert _response(ServerCore(message_store=MessageStore(first_database)), request) == Ack(
        104, AckStatus.STORED
    )

    reopened = _database(tmp_path, "restart.db")
    assert _response(ServerCore(message_store=MessageStore(reopened)), request) == Ack(
        104, AckStatus.ALREADY_STORED
    )
    assert len(
        MessageStore(reopened).get_new_messages(
            callsign="EA3GNU", since=0, limit=20
        ).messages
    ) == 1


def test_invalid_object_field_with_recoverable_id_uses_ack_invalid():
    frame = bytearray(encode_frame(SendMessage(105, 1234, "EA3GNU", "body")))
    frame[17] = ord("e")  # recipient starts after the fixed fields and length byte

    responses = ServerCore().handle_frame("K1ABC", bytes(frame))

    assert len(responses) == 1
    assert decode_frame(responses[0]) == Ack(105, AckStatus.INVALID)


def test_unrecoverable_message_id_uses_error():
    # A complete frame with only seven payload bytes cannot contain message_id.
    frame = b"\x01\x01\x00\x07" + b"\x01" * 7

    responses = ServerCore().handle_frame("K1ABC", frame)

    assert len(responses) == 1
    response = decode_frame(responses[0])
    assert isinstance(response, Error)
    assert response.request_operation == Operation.SEND_MESSAGE
    assert response.error_code == ErrorCode.INVALID_FRAME


def test_missing_store_returns_busy():
    response = _response(ServerCore(), SendMessage(106, 1234, "EA3GNU", "body"))

    assert response == Error(
        Operation.SEND_MESSAGE, ErrorCode.BUSY, "message store unavailable"
    )


def test_authenticated_callsign_is_validated_without_normalization(tmp_path):
    database = _database(tmp_path)
    core = ServerCore(message_store=MessageStore(database))
    request = SendMessage(107, 1234, "EA3GNU", "body")

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

    request = SendMessage(108, 1234, "EA3GNU", "body")

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
