"""Tests for atomic public-bulletin persistence."""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

from openqsp.storage import (
    BulletinStore,
    Database,
    MessageStore,
    SequenceExhaustedError,
    StoreResult,
)
from openqsp.storage.bulletins import bulletin_content_hash
from openqsp.storage.migrations import decode_u64, encode_u64


BULLETIN_A = {
    "bulletin_id": 100,
    "created_at": 500,
    "author": "EA1ABC",
    "title": "Actividad solar \N{SUN WITH FACE}",
    "body": "Próxima apertura en 10 metros \N{SATELLITE ANTENNA}",
}


@pytest.fixture
def database(tmp_path) -> Database:
    database = Database(tmp_path / "node.db")
    database.initialize()
    return database


def _store(database: Database, *, clock=lambda: 1000) -> BulletinStore:
    return BulletinStore(database, clock=clock)


def _sequence_state(database: Database, stream: str = "bulletins") -> int:
    with database.connect() as connection:
        value = connection.execute(
            "SELECT last_value FROM sequences WHERE stream = ?", (stream,)
        ).fetchone()[0]
    return decode_u64(value)


def test_first_and_second_insert_allocate_sequences_and_complete_rows(database) -> None:
    store = _store(database)

    first = store.store_bulletin(**BULLETIN_A)
    second = store.store_bulletin(
        bulletin_id=101,
        created_at=501,
        author="EA2XYZ",
        title="Segundo boletín",
        body="Texto dos",
    )

    assert (first.result, first.sequence) == (StoreResult.STORED, 1)
    assert (second.result, second.sequence) == (StoreResult.STORED, 2)
    with database.connect() as connection:
        objects = connection.execute(
            "SELECT object_id, object_type FROM objects ORDER BY object_id"
        ).fetchall()
        bulletins = connection.execute(
            """SELECT sequence, bulletin_id, created_at, accepted_at, author,
                      title, body, content_hash
               FROM bulletins ORDER BY sequence"""
        ).fetchall()

    assert [(decode_u64(row[0]), row[1]) for row in objects] == [
        (100, "bulletin"),
        (101, "bulletin"),
    ]
    assert [decode_u64(row[0]) for row in bulletins] == [1, 2]
    assert decode_u64(bulletins[0][1]) == 100
    assert tuple(bulletins[0][2:7]) == (
        500,
        1000,
        "EA1ABC",
        BULLETIN_A["title"],
        BULLETIN_A["body"].encode("utf-8"),
    )
    assert len(bulletins[0][7]) == hashlib.sha256().digest_size
    assert bulletins[0][7] == bulletin_content_hash(
        bulletin_id=100,
        created_at=500,
        author="EA1ABC",
        title=BULLETIN_A["title"],
        body=BULLETIN_A["body"].encode("utf-8"),
    )
    assert _sequence_state(database) == 2
    assert _sequence_state(database, "messages") == 0


def test_identical_retry_preserves_sequence_accepted_at_and_hash(database) -> None:
    first = _store(database, clock=lambda: 1000).store_bulletin(**BULLETIN_A)
    with database.connect() as connection:
        original = connection.execute(
            "SELECT sequence, accepted_at, content_hash FROM bulletins"
        ).fetchone()

    retry = _store(database, clock=lambda: 2000).store_bulletin(**BULLETIN_A)

    assert first.sequence == retry.sequence == 1
    assert retry.result is StoreResult.ALREADY_STORED
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT sequence, accepted_at, content_hash FROM bulletins"
        ).fetchall()
    assert len(rows) == 1
    assert tuple(rows[0]) == tuple(original)
    assert rows[0]["accepted_at"] == 1000
    assert _sequence_state(database) == 1


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("title", "Título cambiado"),
        ("body", "Texto cambiado"),
        ("author", "EA8YYY"),
        ("created_at", 501),
    ],
)
def test_changed_canonical_field_is_a_conflict(database, field, replacement) -> None:
    store = _store(database)
    store.store_bulletin(**BULLETIN_A)

    outcome = store.store_bulletin(**{**BULLETIN_A, field: replacement})

    assert (outcome.result, outcome.sequence) == (StoreResult.CONFLICT, None)
    assert _sequence_state(database) == 1
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM bulletins").fetchone()[0] == 1


def test_identifier_owned_by_message_is_a_cross_type_conflict(database) -> None:
    message = MessageStore(database, clock=lambda: 900).store_message(
        message_id=100,
        created_at=400,
        author="EA1ABC",
        recipient="EA2XYZ",
        body="Privado",
    )

    outcome = _store(database).store_bulletin(**BULLETIN_A)

    assert (message.result, message.sequence) == (StoreResult.STORED, 1)
    assert (outcome.result, outcome.sequence) == (StoreResult.CONFLICT, None)
    assert _sequence_state(database) == 0
    assert _sequence_state(database, "messages") == 1
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM bulletins").fetchone()[0] == 0


def test_full_u64_bulletin_id_is_stored(database) -> None:
    outcome = _store(database).store_bulletin(
        **{**BULLETIN_A, "bulletin_id": 0xFFFF_FFFF_FFFF_FFFF}
    )

    assert (outcome.result, outcome.sequence) == (StoreResult.STORED, 1)
    with database.connect() as connection:
        stored_id = connection.execute(
            "SELECT bulletin_id FROM bulletins"
        ).fetchone()[0]
    assert decode_u64(stored_id) == 0xFFFF_FFFF_FFFF_FFFF


def test_retry_after_database_restart_is_idempotent(tmp_path) -> None:
    path = tmp_path / "restart.db"
    first_database = Database(path)
    first_database.initialize()
    _store(first_database, clock=lambda: 1000).store_bulletin(**BULLETIN_A)

    reopened_database = Database(path)
    reopened_database.initialize()
    retry = _store(reopened_database, clock=lambda: 2000).store_bulletin(**BULLETIN_A)

    assert (retry.result, retry.sequence) == (StoreResult.ALREADY_STORED, 1)
    with reopened_database.connect() as connection:
        row = connection.execute(
            "SELECT sequence, accepted_at FROM bulletins"
        ).fetchone()
    assert (decode_u64(row["sequence"]), row["accepted_at"]) == (1, 1000)
    assert _sequence_state(reopened_database) == 1


def test_failure_after_object_insert_rolls_back_every_write(database) -> None:
    with database.connect() as connection:
        connection.execute(
            """CREATE TRIGGER fail_bulletin_insert BEFORE INSERT ON bulletins
               BEGIN SELECT RAISE(ABORT, 'forced bulletin failure'); END"""
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced bulletin failure"):
        _store(database).store_bulletin(**BULLETIN_A)

    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM objects").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM bulletins").fetchone()[0] == 0
        connection.execute("DROP TRIGGER fail_bulletin_insert")
    assert _sequence_state(database) == 0

    outcome = _store(database).store_bulletin(**BULLETIN_A)
    assert (outcome.result, outcome.sequence) == (StoreResult.STORED, 1)


def test_exhausted_sequence_rolls_back_without_an_object(database) -> None:
    with database.connect() as connection:
        connection.execute(
            "UPDATE sequences SET last_value = ? WHERE stream = 'bulletins'",
            (encode_u64(0xFFFF_FFFF_FFFF_FFFF),),
        )

    with pytest.raises(SequenceExhaustedError, match="exhausted"):
        _store(database).store_bulletin(**BULLETIN_A)

    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM objects").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM bulletins").fetchone()[0] == 0
    assert _sequence_state(database) == 0xFFFF_FFFF_FFFF_FFFF


def test_content_hash_is_deterministic_and_field_delimited() -> None:
    common = {"bulletin_id": 1, "created_at": 2, "body": b"body"}
    first = bulletin_content_hash(**common, author="AB", title="C")
    repeated = bulletin_content_hash(**common, author="AB", title="C")
    ambiguous_concatenation = bulletin_content_hash(
        **common, author="A", title="BC"
    )

    assert first == repeated
    assert first != ambiguous_concatenation


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bulletin_id", -1),
        ("bulletin_id", 2**64),
        ("created_at", -1),
        ("created_at", 2**63),
        ("author", b"EA1ABC"),
        ("title", "Título".encode("utf-8")),
        ("body", b"Texto"),
    ],
)
def test_structurally_unrepresentable_inputs_are_rejected(database, field, value) -> None:
    with pytest.raises((TypeError, ValueError)):
        _store(database).store_bulletin(**{**BULLETIN_A, field: value})

    assert _sequence_state(database) == 0


@pytest.mark.parametrize("clock_value", [-1, 2**63, True, "1000"])
def test_invalid_clock_value_rolls_back(database, clock_value) -> None:
    with pytest.raises(ValueError, match="clock"):
        _store(database, clock=lambda: clock_value).store_bulletin(**BULLETIN_A)

    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM objects").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM bulletins").fetchone()[0] == 0
    assert _sequence_state(database) == 0
