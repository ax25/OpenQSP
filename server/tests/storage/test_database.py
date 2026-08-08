"""Tests for SQLite connection and schema infrastructure."""

from __future__ import annotations

import sqlite3

import pytest

from openqsp.storage import Database, UnsupportedSchemaVersionError
from openqsp.storage.migrations import decode_u64, encode_u64, migrate


EXPECTED_TABLES = {"objects", "sequences", "messages", "bulletins"}
EXPECTED_INDEXES = {
    "idx_messages_author_sequence",
    "idx_messages_recipient_sequence",
}


def _schema_names(connection: sqlite3.Connection, kind: str) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_schema WHERE type = ?", (kind,)
    ).fetchall()
    return {str(row[0]) for row in rows}


def test_initialize_new_database_creates_versioned_schema(tmp_path) -> None:
    path = tmp_path / "node.db"
    database = Database(path)

    assert not path.exists()
    database.initialize()

    assert path.exists()
    assert database.get_schema_version() == 1
    with database.connect() as connection:
        assert EXPECTED_TABLES <= _schema_names(connection, "table")
        assert EXPECTED_INDEXES <= _schema_names(connection, "index")


def test_initialize_is_idempotent_and_preserves_data(tmp_path) -> None:
    database = Database(tmp_path / "node.db")
    database.initialize()
    object_id = encode_u64(42)
    with database.connect() as connection:
        connection.execute("BEGIN")
        connection.execute(
            "INSERT INTO objects(object_id, object_type) VALUES (?, 'message')",
            (object_id,),
        )
        connection.commit()

    database.initialize()

    with database.connect() as connection:
        row = connection.execute(
            "SELECT object_type FROM objects WHERE object_id = ?", (object_id,)
        ).fetchone()
    assert row is not None
    assert row[0] == "message"


def test_database_can_be_reopened_and_initialized(tmp_path) -> None:
    path = tmp_path / "node.db"
    Database(path).initialize()

    reopened = Database(path)
    reopened.initialize()

    assert reopened.get_schema_version() == 1
    with reopened.connect() as connection:
        assert EXPECTED_TABLES <= _schema_names(connection, "table")


def test_newer_schema_is_rejected(tmp_path) -> None:
    database = Database(tmp_path / "future.db")
    with database.connect() as connection:
        connection.execute("PRAGMA user_version = 99")

    with pytest.raises(UnsupportedSchemaVersionError, match="99.*newer"):
        database.initialize()


def test_connections_enable_foreign_keys(tmp_path) -> None:
    database = Database(tmp_path / "node.db")
    with database.connect() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_object_ids_are_globally_unique_across_types(tmp_path) -> None:
    database = Database(tmp_path / "node.db")
    database.initialize()
    object_id = encode_u64(123)

    with database.connect() as connection:
        connection.execute("BEGIN")
        connection.execute(
            "INSERT INTO objects(object_id, object_type) VALUES (?, 'message')",
            (object_id,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO objects(object_id, object_type) VALUES (?, 'bulletin')",
                (object_id,),
            )
        connection.rollback()


@pytest.mark.parametrize(
    "number",
    [
        0x0000_0000_0000_0001,
        0x7FFF_FFFF_FFFF_FFFF,
        0x8000_0000_0000_0000,
        0xFFFF_FFFF_FFFF_FFFF,
    ],
)
def test_full_u64_object_id_range_round_trips(tmp_path, number) -> None:
    database = Database(tmp_path / "node.db")
    database.initialize()
    encoded = encode_u64(number)

    with database.connect() as connection:
        connection.execute("BEGIN")
        connection.execute(
            "INSERT INTO objects(object_id, object_type) VALUES (?, 'message')",
            (encoded,),
        )
        connection.commit()
        stored = connection.execute(
            "SELECT object_id FROM objects WHERE object_id = ?", (encoded,)
        ).fetchone()[0]

    assert decode_u64(stored) == number


def test_u64_blob_encoding_preserves_unsigned_order() -> None:
    values = [0, 1, 0x7FFF_FFFF_FFFF_FFFF, 0x8000_0000_0000_0000, 2**64 - 1]
    assert sorted(map(encode_u64, reversed(values))) == list(map(encode_u64, values))


def test_message_and_bulletin_sequence_state_is_independent(tmp_path) -> None:
    database = Database(tmp_path / "node.db")
    database.initialize()

    with database.connect() as connection:
        connection.execute("BEGIN")
        connection.execute(
            "UPDATE sequences SET last_value = ? WHERE stream = 'messages'",
            (encode_u64(7),),
        )
        connection.commit()
        rows = connection.execute(
            "SELECT stream, last_value FROM sequences ORDER BY stream"
        ).fetchall()

    state = {row[0]: decode_u64(row[1]) for row in rows}
    assert state == {"bulletins": 0, "messages": 7}

    with database.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="move backwards"):
            connection.execute(
                "UPDATE sequences SET last_value = ? WHERE stream = 'messages'",
                (encode_u64(6),),
            )


def test_migration_failure_rolls_back_schema_and_version() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    failing_migration = {
        1: (
            "CREATE TABLE temporary_table(value INTEGER)",
            "THIS IS NOT SQL",
        )
    }

    with pytest.raises(sqlite3.OperationalError):
        migrate(connection, 0, migrations=failing_migration)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
    assert "temporary_table" not in _schema_names(connection, "table")


def test_subtype_rows_must_match_registered_object_type(tmp_path) -> None:
    database = Database(tmp_path / "node.db")
    database.initialize()
    object_id = encode_u64(5)

    with database.connect() as connection:
        connection.execute("BEGIN")
        connection.execute(
            "INSERT INTO objects(object_id, object_type) VALUES (?, 'bulletin')",
            (object_id,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="message object"):
            connection.execute(
                """INSERT INTO messages(
                       sequence, message_id, created_at, accepted_at,
                       author, recipient, body, content_hash
                   ) VALUES (?, ?, 1, 1, 'EA1ABC', 'EA2XYZ', X'01', X'02')""",
                (encode_u64(1), object_id),
            )
        connection.rollback()
