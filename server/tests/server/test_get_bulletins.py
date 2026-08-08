"""Milestone 3.4 tests for bulletin retrieval through the server core."""

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
    GetNewMessages,
    Message,
    Operation,
    SendMessage,
    decode_frame,
    encode_frame,
)
from openqsp.server import ServerCore
from openqsp.storage import BulletinStore, Database, MessageStore, StorageIntegrityError


def _database(tmp_path, name="node.db"):
    database = Database(tmp_path / name)
    database.initialize()
    return database


def _store_bulletin(store, bulletin_id, *, author="EA9SRC"):
    outcome = store.store_bulletin(
        bulletin_id=bulletin_id,
        created_at=1_000 + bulletin_id,
        author=author,
        title=f"title {bulletin_id} — exact",
        body=f"body {bulletin_id} — not a header",
    )
    return outcome.sequence


def _new_responses(core, *, callsign="EA3GNU", since=0, maximum=20):
    frames = core.handle_frame(
        callsign, encode_frame(GetNewBulletins(since, maximum))
    )
    return [decode_frame(frame) for frame in frames]


def _bulletin_response(core, bulletin_id, *, callsign="EA3GNU"):
    frames = core.handle_frame(callsign, encode_frame(GetBulletin(bulletin_id)))
    return [decode_frame(frame) for frame in frames]


def test_empty_store_returns_exactly_one_end(tmp_path):
    core = ServerCore(bulletin_store=BulletinStore(_database(tmp_path)))

    assert _new_responses(core) == [
        End(Operation.GET_NEW_BULLETINS, 0, 0, False)
    ]


def test_headers_preserve_all_stored_fields_and_order_without_bodies(tmp_path):
    store = BulletinStore(_database(tmp_path))
    sequences = [_store_bulletin(store, bulletin_id) for bulletin_id in (3, 1, 2)]
    persisted = store.get_new_bulletins(since=0, limit=20).headers

    responses = _new_responses(ServerCore(bulletin_store=store))

    assert responses[:-1] == [
        BulletinHeader(
            header.sequence,
            header.bulletin_id,
            header.created_at,
            header.author,
            header.title,
        )
        for header in persisted
    ]
    assert [header.sequence for header in responses[:-1]] == sequences
    assert all(not hasattr(header, "body") for header in responses[:-1])
    assert responses[-1] == End(
        Operation.GET_NEW_BULLETINS, 3, sequences[-1], False
    )


def test_header_pagination_then_empty_page_has_no_duplicates(tmp_path):
    store = BulletinStore(_database(tmp_path))
    sequences = [_store_bulletin(store, bulletin_id) for bulletin_id in (1, 2, 3)]
    core = ServerCore(bulletin_store=store)

    first = _new_responses(core, maximum=2)
    second = _new_responses(core, since=first[-1].next_since, maximum=2)
    empty = _new_responses(core, since=second[-1].next_since, maximum=2)

    assert [header.sequence for header in first[:-1]] == sequences[:2]
    assert first[-1] == End(Operation.GET_NEW_BULLETINS, 2, sequences[1], True)
    assert [header.sequence for header in second[:-1]] == sequences[2:]
    assert second[-1] == End(Operation.GET_NEW_BULLETINS, 1, sequences[2], False)
    assert empty == [End(Operation.GET_NEW_BULLETINS, 0, sequences[2], False)]


def test_invalid_cursor_returns_error_without_end(tmp_path):
    store = BulletinStore(_database(tmp_path))
    _store_bulletin(store, 1)

    assert _new_responses(ServerCore(bulletin_store=store), since=2) == [
        Error(
            Operation.GET_NEW_BULLETINS,
            ErrorCode.INVALID_CURSOR,
            "invalid bulletin cursor",
        )
    ]


def test_complete_bulletin_preserves_every_stored_field_and_is_public(tmp_path):
    store = BulletinStore(_database(tmp_path))
    _store_bulletin(store, 42, author="F4XYZ")
    persisted = store.get_bulletin(bulletin_id=42)
    expected = Bulletin(
        persisted.bulletin_id,
        persisted.created_at,
        persisted.author,
        persisted.title,
        persisted.body,
    )
    core = ServerCore(bulletin_store=store)

    assert _bulletin_response(core, 42, callsign="EA3GNU") == [expected]
    assert _bulletin_response(core, 42, callsign="K1ABC") == [expected]
    assert _new_responses(core, callsign="EA3GNU")[:-1] == _new_responses(
        core, callsign="K1ABC"
    )[:-1]


def test_missing_and_private_message_ids_are_bulletin_not_found(tmp_path):
    database = _database(tmp_path)
    MessageStore(database).store_message(
        message_id=77,
        created_at=100,
        author="K1ABC",
        recipient="EA3GNU",
        body="private",
    )
    core = ServerCore(bulletin_store=BulletinStore(database))
    expected = [
        Error(Operation.GET_BULLETIN, ErrorCode.NOT_FOUND, "bulletin not found")
    ]

    assert _bulletin_response(core, 99) == expected
    assert _bulletin_response(core, 77) == expected


def test_missing_store_returns_busy_for_both_operations():
    assert _new_responses(ServerCore()) == [
        Error(
            Operation.GET_NEW_BULLETINS,
            ErrorCode.BUSY,
            "bulletin store unavailable",
        )
    ]
    assert _bulletin_response(ServerCore(), 1) == [
        Error(Operation.GET_BULLETIN, ErrorCode.BUSY, "bulletin store unavailable")
    ]


def test_invalid_identity_does_not_access_bulletin_storage():
    class UntouchedStore:
        def __getattr__(self, name):
            raise AssertionError(f"storage must not be accessed: {name}")

    core = ServerCore(bulletin_store=UntouchedStore())

    assert _new_responses(core, callsign="ea3gnu") == [
        Error(
            Operation.GET_NEW_BULLETINS,
            ErrorCode.UNAUTHORIZED,
            "invalid authenticated callsign",
        )
    ]
    assert _bulletin_response(core, 1, callsign="EA3GNU-1") == [
        Error(
            Operation.GET_BULLETIN,
            ErrorCode.UNAUTHORIZED,
            "invalid authenticated callsign",
        )
    ]


def test_storage_integrity_errors_return_only_internal_error():
    class CorruptStore:
        def get_new_bulletins(self, **kwargs):
            raise StorageIntegrityError("corrupt headers")

        def get_bulletin(self, **kwargs):
            raise StorageIntegrityError("corrupt bulletin")

    core = ServerCore(bulletin_store=CorruptStore())

    assert _new_responses(core) == [
        Error(
            Operation.GET_NEW_BULLETINS,
            ErrorCode.INTERNAL_ERROR,
            "bulletin storage integrity failure",
        )
    ]
    assert _bulletin_response(core, 1) == [
        Error(
            Operation.GET_BULLETIN,
            ErrorCode.INTERNAL_ERROR,
            "bulletin storage integrity failure",
        )
    ]


def test_bulletin_retrieval_survives_database_restart(tmp_path):
    database = _database(tmp_path, "restart.db")
    sequence = _store_bulletin(BulletinStore(database), 15)

    reopened = _database(tmp_path, "restart.db")
    core = ServerCore(bulletin_store=BulletinStore(reopened))

    headers = _new_responses(core)
    assert headers[-1] == End(Operation.GET_NEW_BULLETINS, 1, sequence, False)
    assert _bulletin_response(core, 15) == [
        Bulletin(15, 1_015, "EA9SRC", "title 15 — exact", "body 15 — not a header")
    ]


def test_all_milestone_three_operations_share_one_persistent_node(tmp_path):
    database = _database(tmp_path)
    bulletin_store = BulletinStore(database)
    _store_bulletin(bulletin_store, 20)
    core = ServerCore(
        message_store=MessageStore(database), bulletin_store=bulletin_store
    )

    send = [
        decode_frame(frame)
        for frame in core.handle_frame(
            "K1ABC", encode_frame(SendMessage(10, 500, "EA3GNU", "hello"))
        )
    ]
    messages = [
        decode_frame(frame)
        for frame in core.handle_frame(
            "EA3GNU", encode_frame(GetNewMessages(0, 20))
        )
    ]

    assert send == [Ack(10, AckStatus.STORED)]
    assert messages == [
        Message(1, 10, 500, "K1ABC", "EA3GNU", "hello"),
        End(Operation.GET_NEW_MESSAGES, 1, 1, False),
    ]
    assert isinstance(_new_responses(core)[0], BulletinHeader)
    assert isinstance(_bulletin_response(core, 20)[0], Bulletin)
