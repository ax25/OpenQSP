"""End-to-end conformance scenarios for the complete persistent object store."""

from __future__ import annotations

import sqlite3

import pytest

from openqsp.storage import (
    BulletinStore,
    Database,
    InvalidCursorError,
    LATEST_SCHEMA_VERSION,
    MessageStore,
    StoreResult,
)
from openqsp.storage.migrations import decode_u64


def _message(message_id: int, recipient: str = "EA1AAA", **changes):
    values = {
        "message_id": message_id,
        "created_at": 100 + message_id % 100,
        "author": "EA0SRC",
        "recipient": recipient,
        "body": f"message {message_id}",
    }
    values.update(changes)
    return values


def _bulletin(bulletin_id: int, **changes):
    values = {
        "bulletin_id": bulletin_id,
        "created_at": 200 + bulletin_id % 100,
        "author": "EA0SRC",
        "title": f"bulletin {bulletin_id}",
        "body": f"body {bulletin_id}",
    }
    values.update(changes)
    return values


def _stores(path, accepted_at=1000):
    database = Database(path)
    database.initialize()
    return (
        database,
        MessageStore(database, clock=lambda: accepted_at),
        BulletinStore(database, clock=lambda: accepted_at),
    )


def _sequence(database: Database, stream: str) -> int:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT last_value FROM sequences WHERE stream = ?", (stream,)
        ).fetchone()
    return decode_u64(row[0])


def _counts(database: Database) -> tuple[int, int, int]:
    with database.connect() as connection:
        return tuple(
            connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("objects", "messages", "bulletins")
        )


def test_full_persistence_lifecycle_and_independent_sequences(tmp_path) -> None:
    path = tmp_path / "lifecycle.db"
    _, messages, bulletins = _stores(path)
    assert [messages.store_message(**_message(i)).sequence for i in (10, 11)] == [1, 2]
    assert [bulletins.store_bulletin(**_bulletin(i)).sequence for i in (20, 21)] == [1, 2]

    # Recreate every public storage object, just as a restarted process would.
    database, messages, bulletins = _stores(path, accepted_at=2000)
    message_page = messages.get_new_messages(callsign="EA1AAA", since=0, limit=20)
    bulletin_page = bulletins.get_new_bulletins(since=0, limit=20)
    assert [item.message_id for item in message_page.messages] == [10, 11]
    assert [item.sequence for item in message_page.messages] == [1, 2]
    assert (message_page.next_since, message_page.has_more) == (2, False)
    assert [item.bulletin_id for item in bulletin_page.headers] == [20, 21]
    assert [item.sequence for item in bulletin_page.headers] == [1, 2]
    assert bulletins.get_bulletin(bulletin_id=20).body == "body 20"
    assert bulletins.get_bulletin(bulletin_id=21).title == "bulletin 21"

    assert messages.store_message(**_message(12)).sequence == 3
    assert bulletins.store_bulletin(**_bulletin(22)).sequence == 3
    assert (_sequence(database, "messages"), _sequence(database, "bulletins")) == (3, 3)


def test_retry_and_conflict_after_restart_preserve_original_metadata(tmp_path) -> None:
    path = tmp_path / "retry.db"
    database, messages, bulletins = _stores(path, accepted_at=1000)
    message = _message(100, body="A")
    bulletin = _bulletin(200, body="A")
    assert messages.store_message(**message).result is StoreResult.STORED
    assert bulletins.store_bulletin(**bulletin).result is StoreResult.STORED

    database, messages, bulletins = _stores(path, accepted_at=9999)
    message_retry = messages.store_message(**message)
    bulletin_retry = bulletins.store_bulletin(**bulletin)
    assert (message_retry.result, message_retry.sequence) == (StoreResult.ALREADY_STORED, 1)
    assert (bulletin_retry.result, bulletin_retry.sequence) == (StoreResult.ALREADY_STORED, 1)
    assert messages.store_message(**{**message, "body": "B"}).result is StoreResult.CONFLICT
    assert bulletins.store_bulletin(**{**bulletin, "body": "B"}).result is StoreResult.CONFLICT
    with database.connect() as connection:
        stored_message = connection.execute(
            "SELECT sequence, accepted_at, body FROM messages"
        ).fetchone()
        stored_bulletin = connection.execute(
            "SELECT sequence, accepted_at, body FROM bulletins"
        ).fetchone()
    assert (decode_u64(stored_message[0]), stored_message[1], bytes(stored_message[2])) == (1, 1000, b"A")
    assert (decode_u64(stored_bulletin[0]), stored_bulletin[1], bytes(stored_bulletin[2])) == (1, 1000, b"A")


@pytest.mark.parametrize("first_type,object_id", [("message", 500), ("bulletin", 600)])
def test_global_id_collision_uses_public_apis_without_advancing_rejected_stream(
    tmp_path, first_type, object_id
) -> None:
    database, messages, bulletins = _stores(tmp_path / f"{first_type}.db")
    if first_type == "message":
        original = messages.store_message(**_message(object_id))
        rejected = bulletins.store_bulletin(**_bulletin(object_id))
        expected_sequences = (1, 0)
    else:
        original = bulletins.store_bulletin(**_bulletin(object_id))
        rejected = messages.store_message(**_message(object_id))
        expected_sequences = (0, 1)
    assert original.result is StoreResult.STORED
    assert rejected.result is StoreResult.CONFLICT
    assert (_sequence(database, "messages"), _sequence(database, "bulletins")) == expected_sequences
    assert _counts(database)[0] == 1
    assert sum(_counts(database)[1:]) == 1


def test_interleaved_streams_continue_independently_after_restart(tmp_path) -> None:
    path = tmp_path / "streams.db"
    _, messages, bulletins = _stores(path)
    outcomes = [
        messages.store_message(**_message(1)).sequence,
        bulletins.store_bulletin(**_bulletin(101)).sequence,
        messages.store_message(**_message(2)).sequence,
        bulletins.store_bulletin(**_bulletin(102)).sequence,
        messages.store_message(**_message(3)).sequence,
    ]
    assert outcomes == [1, 1, 2, 2, 3]
    _, messages, bulletins = _stores(path)
    assert messages.store_message(**_message(4)).sequence == 4
    assert bulletins.store_bulletin(**_bulletin(103)).sequence == 3


def test_message_filtering_pagination_and_empty_page_cursor(tmp_path) -> None:
    _, messages, _ = _stores(tmp_path / "mailbox.db")
    recipients = ["EA1AAA", "EA2BBB", "EA1AAA", "EA1AAA", "EA2BBB"]
    for object_id, recipient in enumerate(recipients, start=1):
        messages.store_message(**_message(object_id, recipient))

    first = messages.get_new_messages(callsign="EA1AAA", since=0, limit=2)
    second = messages.get_new_messages(callsign="EA1AAA", since=3, limit=2)
    for object_id in range(6, 11):
        messages.store_message(**_message(object_id, "EA2BBB"))
    empty = messages.get_new_messages(callsign="EA1AAA", since=8, limit=2)
    assert ([item.sequence for item in first.messages], first.next_since, first.has_more) == ([1, 3], 3, True)
    assert ([item.sequence for item in second.messages], second.next_since, second.has_more) == ([4], 4, False)
    assert (empty.messages, empty.next_since, empty.has_more) == ((), 8, False)


def test_bulletin_pagination_and_empty_page_cursor(tmp_path) -> None:
    _, _, bulletins = _stores(tmp_path / "bulletin-pages.db")
    for object_id in range(1, 6):
        bulletins.store_bulletin(**_bulletin(object_id))
    pages = [bulletins.get_new_bulletins(since=since, limit=2) for since in (0, 2, 4, 5)]
    assert [([h.sequence for h in page.headers], page.next_since, page.has_more) for page in pages] == [
        ([1, 2], 2, True), ([3, 4], 4, True), ([5], 5, False), ([], 5, False)
    ]


def test_empty_and_populated_stores_reject_cursors_beyond_stream_state(tmp_path) -> None:
    _, messages, bulletins = _stores(tmp_path / "cursors.db")
    assert messages.get_new_messages(callsign="EA1AAA", since=0, limit=1).messages == ()
    assert bulletins.get_new_bulletins(since=0, limit=1).headers == ()
    with pytest.raises(InvalidCursorError):
        messages.get_new_messages(callsign="EA1AAA", since=1, limit=1)
    with pytest.raises(InvalidCursorError):
        bulletins.get_new_bulletins(since=1, limit=1)
    messages.store_message(**_message(1))
    bulletins.store_bulletin(**_bulletin(2))
    with pytest.raises(InvalidCursorError):
        messages.get_new_messages(callsign="EA1AAA", since=2, limit=1)
    with pytest.raises(InvalidCursorError):
        bulletins.get_new_bulletins(since=2, limit=1)


def test_failed_transaction_leaves_no_partial_object_or_sequence_gap(tmp_path) -> None:
    database, messages, _ = _stores(tmp_path / "rollback.db")
    for object_id in range(1, 4):
        assert messages.store_message(**_message(object_id)).sequence == object_id
    with database.connect() as connection:
        connection.execute(
            """CREATE TRIGGER conformance_failure BEFORE INSERT ON messages
               WHEN NEW.message_id = X'0000000000000004'
               BEGIN SELECT RAISE(ABORT, 'forced conformance failure'); END"""
        )
    with pytest.raises(sqlite3.IntegrityError, match="forced conformance failure"):
        messages.store_message(**_message(4))
    assert _counts(database) == (3, 3, 0)
    assert _sequence(database, "messages") == 3
    with database.connect() as connection:
        connection.execute("DROP TRIGGER conformance_failure")
    assert messages.store_message(**_message(5)).sequence == 4


def test_database_connections_use_durable_configuration_and_schema_v1(tmp_path) -> None:
    database, _, _ = _stores(tmp_path / "durability.db")
    with database.connect() as connection:
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]
    assert foreign_keys == 1
    assert str(journal_mode).lower() == "wal"
    assert synchronous == 2  # SQLite's portable numeric value for FULL.
    assert LATEST_SCHEMA_VERSION == database.get_schema_version() == 1


def test_high_u64_ids_survive_restart_retry_and_retrieval(tmp_path) -> None:
    path = tmp_path / "u64.db"
    _, messages, bulletins = _stores(path)
    high_bit = 0x8000_0000_0000_0000
    maximum = 0xFFFF_FFFF_FFFF_FFFF
    message = _message(high_bit)
    bulletin = _bulletin(maximum)
    messages.store_message(**message)
    bulletins.store_bulletin(**bulletin)

    _, messages, bulletins = _stores(path, accepted_at=2000)
    assert messages.store_message(**message).result is StoreResult.ALREADY_STORED
    assert bulletins.store_bulletin(**bulletin).result is StoreResult.ALREADY_STORED
    assert messages.get_new_messages(callsign="EA1AAA", since=0, limit=1).messages[0].message_id == high_bit
    assert bulletins.get_bulletin(bulletin_id=maximum).bulletin_id == maximum


@pytest.mark.parametrize("object_type", ["message", "bulletin"])
def test_repeated_retries_never_duplicate_rows_or_advance_sequences(tmp_path, object_type) -> None:
    database, messages, bulletins = _stores(tmp_path / f"retry-{object_type}.db")
    if object_type == "message":
        operation, value, stream = messages.store_message, _message(77), "messages"
    else:
        operation, value, stream = bulletins.store_bulletin, _bulletin(77), "bulletins"
    outcomes = [operation(**value) for _ in range(4)]
    assert [outcome.result for outcome in outcomes] == [StoreResult.STORED] + [StoreResult.ALREADY_STORED] * 3
    assert [outcome.sequence for outcome in outcomes] == [1, 1, 1, 1]
    assert _counts(database)[0] == 1
    assert sum(_counts(database)[1:]) == 1
    assert _sequence(database, stream) == 1
