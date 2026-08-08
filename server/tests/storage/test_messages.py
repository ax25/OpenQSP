"""Tests for atomic private-message persistence."""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

from openqsp.storage import (
    Database,
    MessageStore,
    SequenceExhaustedError,
    StoreResult,
)
from openqsp.storage.messages import message_content_hash
from openqsp.storage.migrations import decode_u64, encode_u64


MESSAGE_A = {
    "message_id": 100,
    "created_at": 500,
    "author": "EA1ABC",
    "recipient": "EA2XYZ",
    "body": "Hola \N{EARTH GLOBE EUROPE-AFRICA}",
}


@pytest.fixture
def database(tmp_path) -> Database:
    database = Database(tmp_path / "node.db")
    database.initialize()
    return database


def _store(database: Database, *, clock=lambda: 1000) -> MessageStore:
    return MessageStore(database, clock=clock)


def _sequence_state(database: Database, stream: str = "messages") -> int:
    with database.connect() as connection:
        value = connection.execute(
            "SELECT last_value FROM sequences WHERE stream = ?", (stream,)
        ).fetchone()[0]
    return decode_u64(value)


def test_first_and_second_insert_allocate_sequences_and_complete_rows(database) -> None:
    store = _store(database)

    first = store.store_message(**MESSAGE_A)
    second = store.store_message(
        message_id=101,
        created_at=501,
        author="EA3DEF",
        recipient="EA4UVW",
        body="Segundo",
    )

    assert (first.result, first.sequence) == (StoreResult.STORED, 1)
    assert (second.result, second.sequence) == (StoreResult.STORED, 2)
    with database.connect() as connection:
        objects = connection.execute(
            "SELECT object_id, object_type FROM objects ORDER BY object_id"
        ).fetchall()
        messages = connection.execute(
            """SELECT sequence, message_id, created_at, accepted_at, author,
                      recipient, body, content_hash
               FROM messages ORDER BY sequence"""
        ).fetchall()
    assert [(decode_u64(row[0]), row[1]) for row in objects] == [
        (100, "message"),
        (101, "message"),
    ]
    assert [decode_u64(row[0]) for row in messages] == [1, 2]
    assert decode_u64(messages[0][1]) == 100
    assert tuple(messages[0][2:7]) == (
        500,
        1000,
        "EA1ABC",
        "EA2XYZ",
        MESSAGE_A["body"].encode("utf-8"),
    )
    assert len(messages[0][7]) == hashlib.sha256().digest_size
    assert messages[0][7] == message_content_hash(
        message_id=100,
        created_at=500,
        author="EA1ABC",
        recipient="EA2XYZ",
        body=MESSAGE_A["body"].encode("utf-8"),
    )
    assert _sequence_state(database) == 2
    assert _sequence_state(database, "bulletins") == 0


def test_identical_retry_preserves_sequence_accepted_at_and_hash(database) -> None:
    first = _store(database, clock=lambda: 1000).store_message(**MESSAGE_A)
    with database.connect() as connection:
        original = connection.execute(
            "SELECT sequence, accepted_at, content_hash FROM messages"
        ).fetchone()

    retry = _store(database, clock=lambda: 2000).store_message(**MESSAGE_A)

    assert first.sequence == retry.sequence == 1
    assert retry.result is StoreResult.ALREADY_STORED
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT sequence, accepted_at, content_hash FROM messages"
        ).fetchall()
    assert len(rows) == 1
    assert tuple(rows[0]) == tuple(original)
    assert rows[0]["accepted_at"] == 1000
    assert _sequence_state(database) == 1


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("body", "Adios"),
        ("recipient", "EA9ZZZ"),
        ("author", "EA8YYY"),
        ("created_at", 501),
    ],
)
def test_changed_canonical_field_is_a_conflict(database, field, replacement) -> None:
    store = _store(database)
    store.store_message(**MESSAGE_A)
    changed = {**MESSAGE_A, field: replacement}

    outcome = store.store_message(**changed)

    assert (outcome.result, outcome.sequence) == (StoreResult.CONFLICT, None)
    assert _sequence_state(database) == 1
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 1


def test_identifier_owned_by_bulletin_is_a_conflict(database) -> None:
    with database.connect() as connection:
        connection.execute("BEGIN")
        connection.execute(
            "INSERT INTO objects(object_id, object_type) VALUES (?, 'bulletin')",
            (encode_u64(MESSAGE_A["message_id"]),),
        )
        connection.commit()

    outcome = _store(database).store_message(**MESSAGE_A)

    assert (outcome.result, outcome.sequence) == (StoreResult.CONFLICT, None)
    assert _sequence_state(database) == 0


def test_full_u64_message_id_is_stored(database) -> None:
    outcome = _store(database).store_message(
        **{**MESSAGE_A, "message_id": 0xFFFF_FFFF_FFFF_FFFF}
    )

    assert outcome.sequence == 1
    with database.connect() as connection:
        stored_id = connection.execute("SELECT message_id FROM messages").fetchone()[0]
    assert decode_u64(stored_id) == 0xFFFF_FFFF_FFFF_FFFF


def test_retry_after_database_restart_is_idempotent(tmp_path) -> None:
    path = tmp_path / "restart.db"
    first_database = Database(path)
    first_database.initialize()
    _store(first_database, clock=lambda: 1000).store_message(**MESSAGE_A)

    reopened_database = Database(path)
    reopened_database.initialize()
    retry = _store(reopened_database, clock=lambda: 2000).store_message(**MESSAGE_A)

    assert (retry.result, retry.sequence) == (StoreResult.ALREADY_STORED, 1)
    with reopened_database.connect() as connection:
        row = connection.execute(
            "SELECT sequence, accepted_at FROM messages"
        ).fetchone()
    assert (decode_u64(row["sequence"]), row["accepted_at"]) == (1, 1000)
    assert _sequence_state(reopened_database) == 1


def test_failure_after_object_insert_rolls_back_every_write(database) -> None:
    with database.connect() as connection:
        connection.execute(
            """CREATE TRIGGER fail_message_insert BEFORE INSERT ON messages
               BEGIN SELECT RAISE(ABORT, 'forced message failure'); END"""
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced message failure"):
        _store(database).store_message(**MESSAGE_A)

    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM objects").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        connection.execute("DROP TRIGGER fail_message_insert")
    assert _sequence_state(database) == 0

    outcome = _store(database).store_message(**MESSAGE_A)
    assert (outcome.result, outcome.sequence) == (StoreResult.STORED, 1)


def test_exhausted_sequence_rolls_back_without_an_object(database) -> None:
    with database.connect() as connection:
        connection.execute(
            "UPDATE sequences SET last_value = ? WHERE stream = 'messages'",
            (encode_u64(0xFFFF_FFFF_FFFF_FFFF),),
        )

    with pytest.raises(SequenceExhaustedError, match="exhausted"):
        _store(database).store_message(**MESSAGE_A)

    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM objects").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    assert _sequence_state(database) == 0xFFFF_FFFF_FFFF_FFFF


def test_content_hash_is_deterministic_and_field_delimited() -> None:
    common = {"message_id": 1, "created_at": 2}
    first = message_content_hash(
        **common, author="AB", recipient="C", body=b"body"
    )
    repeated = message_content_hash(
        **common, author="AB", recipient="C", body=b"body"
    )
    ambiguous_concatenation = message_content_hash(
        **common, author="A", recipient="BC", body=b"body"
    )

    assert first == repeated
    assert first != ambiguous_concatenation


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("message_id", -1),
        ("message_id", 2**64),
        ("created_at", -1),
        ("created_at", 2**63),
    ],
)
def test_structurally_unrepresentable_inputs_are_rejected(database, field, value) -> None:
    values = {**MESSAGE_A, field: value}

    with pytest.raises(ValueError):
        _store(database).store_message(**values)

    assert _sequence_state(database) == 0
