"""Milestone 3.3 tests for GET_NEW_MESSAGES server-core handling."""

from __future__ import annotations

from openqsp.protocol import (
    End,
    Error,
    ErrorCode,
    GetNewMessages,
    Message,
    Operation,
    decode_frame,
    encode_frame,
)
from openqsp.server import ServerCore
from openqsp.storage import Database, MessageStore, StorageIntegrityError


def _database(tmp_path, name="node.db") -> Database:
    database = Database(tmp_path / name)
    database.initialize()
    return database


def _store_message(store, sequence, recipient, *, author="EA9SRC"):
    outcome = store.store_message(

        created_at=1_000 + sequence,
        author=author,
        recipient=recipient,
        body=f"body {sequence} — exact",
    )
    return outcome


def _responses(core, *, callsign="EA3GNU", since=0, maximum=20):
    frames = core.handle_frame(callsign, encode_frame(GetNewMessages(since, maximum)))
    return [decode_frame(frame) for frame in frames]


def test_empty_mailbox_returns_exactly_one_end(tmp_path):
    responses = _responses(ServerCore(message_store=MessageStore(_database(tmp_path))))

    assert responses == [End(Operation.GET_NEW_MESSAGES, 0, 0, False)]


def test_single_message_maps_every_persisted_field_then_end(tmp_path):
    store = MessageStore(_database(tmp_path), clock=lambda: 2_000)
    sequence = _store_message(store, 101, "EA3GNU")
    persisted = store.get_new_messages(callsign="EA3GNU", since=0, limit=20).messages[0]

    responses = _responses(ServerCore(message_store=store))

    assert responses == [
        Message(persisted.sequence, persisted.created_at,
            persisted.author,
            persisted.recipient,
            persisted.body,
        ),
        End(Operation.GET_NEW_MESSAGES, 1, sequence, False),
    ]


def test_multiple_messages_preserve_ascending_storage_order(tmp_path):
    store = MessageStore(_database(tmp_path))
    sequences = [
        _store_message(store, sequence, "EA3GNU") for sequence in (1, 2, 3)
    ]

    responses = _responses(ServerCore(message_store=store))

    assert [response.sequence for response in responses[:-1]] == sequences
    assert all(isinstance(response, Message) for response in responses[:-1])
    assert responses[-1] == End(Operation.GET_NEW_MESSAGES, 3, sequences[-1], False)


def test_authenticated_recipient_isolation_with_invisible_global_sequences(tmp_path):
    store = MessageStore(_database(tmp_path))
    first = _store_message(store, 1, "EA3GNU")
    middle = _store_message(store, 2, "EA3ABC")
    last = _store_message(store, 3, "EA3GNU")
    core = ServerCore(message_store=store)

    gnu = _responses(core, callsign="EA3GNU")
    abc = _responses(core, callsign="EA3ABC")

    assert [message.sequence for message in gnu[:-1]] == [first, last]
    assert [message.recipient for message in gnu[:-1]] == ["EA3GNU", "EA3GNU"]
    assert gnu[-1] == End(Operation.GET_NEW_MESSAGES, 2, last, False)
    assert [message.sequence for message in abc[:-1]] == [middle]
    assert [message.recipient for message in abc[:-1]] == ["EA3ABC"]
    assert abc[-1] == End(Operation.GET_NEW_MESSAGES, 1, middle, False)


def test_pagination_then_empty_page_has_no_duplicates(tmp_path):
    store = MessageStore(_database(tmp_path))
    sequences = [
        _store_message(store, sequence, "EA3GNU") for sequence in (1, 2, 3)
    ]
    core = ServerCore(message_store=store)

    first = _responses(core, maximum=2)
    second = _responses(core, since=first[-1].next_since, maximum=2)
    empty = _responses(core, since=second[-1].next_since, maximum=2)

    assert [message.sequence for message in first[:-1]] == sequences[:2]
    assert first[-1] == End(Operation.GET_NEW_MESSAGES, 2, sequences[1], True)
    assert [message.sequence for message in second[:-1]] == sequences[2:]
    assert second[-1] == End(Operation.GET_NEW_MESSAGES, 1, sequences[2], False)
    assert empty == [End(Operation.GET_NEW_MESSAGES, 0, sequences[2], False)]


def test_invalid_global_cursor_returns_error_without_end(tmp_path):
    store = MessageStore(_database(tmp_path))
    _store_message(store, 1, "EA3GNU")

    assert _responses(ServerCore(message_store=store), since=2) == [
        Error(
            Operation.GET_NEW_MESSAGES,
            ErrorCode.INVALID_CURSOR,
            "invalid message cursor",
        )
    ]


def test_missing_store_returns_busy():
    assert _responses(ServerCore()) == [
        Error(Operation.GET_NEW_MESSAGES, ErrorCode.BUSY, "message store unavailable")
    ]


def test_invalid_authenticated_callsign_does_not_reach_storage():
    class UntouchedStore:
        def get_new_messages(self, **kwargs):
            raise AssertionError("storage must not be reached")

    assert _responses(
        ServerCore(message_store=UntouchedStore()), callsign="ea3gnu"
    ) == [
        Error(
            Operation.GET_NEW_MESSAGES,
            ErrorCode.UNAUTHORIZED,
            "invalid authenticated callsign",
        )
    ]


def test_storage_integrity_failure_returns_error_without_partial_messages():
    class CorruptStore:
        def get_new_messages(self, **kwargs):
            raise StorageIntegrityError("corrupt private data")

    assert _responses(ServerCore(message_store=CorruptStore())) == [
        Error(
            Operation.GET_NEW_MESSAGES,
            ErrorCode.INTERNAL_ERROR,
            "message storage integrity failure",
        )
    ]


def test_retrieval_survives_database_restart(tmp_path):
    database = _database(tmp_path, "restart.db")
    store = MessageStore(database)
    sequences = [_store_message(store, sequence, "EA3GNU") for sequence in (1, 2)]

    reopened = _database(tmp_path, "restart.db")
    responses = _responses(ServerCore(message_store=MessageStore(reopened)))

    assert [message.sequence for message in responses[:-1]] == sequences
    assert responses[-1] == End(Operation.GET_NEW_MESSAGES, 2, sequences[-1], False)
