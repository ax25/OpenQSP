"""Schema, connection durability, and ordered migration tests."""

import hashlib
import sqlite3

import pytest
from openqsp.storage import (
    BulletinStore,
    Database,
    MessageStore,
    UnsupportedSchemaVersionError,
)
from openqsp.storage.migrations import (
    LATEST_SCHEMA_VERSION,
    MIGRATIONS,
    encode_u64,
    migrate,
)

V2_TABLES = {"messages", "mailbox_sequences", "bulletins", "bulletin_sequence"}
V3_TABLES = V2_TABLES | {"accounts"}
V4_TABLES = V3_TABLES | {"api_message_sequence", "api_idempotency"}
V5_TABLES = V4_TABLES | {"conversation_reads", "deliveries"}
MIGRATION_1_DIGEST = "12be5fcae6e0a0267b3c7bbcfbfdc5cb7e109be07080cce067c1de39bd8b7777"


def schema_names(connection, kind="table"):
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type=?", (kind,)
        )
    }


def create_v1(path):
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    migrate(connection, 0, target_version=1)
    return connection


def add_v1_message(
    connection, sequence, object_id, recipient, *, author="SRC", accepted_at=500
):
    encoded_id = encode_u64(object_id)
    connection.execute("INSERT INTO objects VALUES (?, 'message')", (encoded_id,))
    connection.execute(
        "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)",
        (
            encode_u64(sequence),
            encoded_id,
            100 + sequence,
            accepted_at,
            author,
            recipient,
            f"message {sequence}".encode(),
            b"old hash",
        ),
    )


def add_v1_bulletin(connection, sequence, object_id, *, author="NEWS", accepted_at=600):
    encoded_id = encode_u64(object_id)
    connection.execute("INSERT INTO objects VALUES (?, 'bulletin')", (encoded_id,))
    connection.execute(
        "INSERT INTO bulletins VALUES (?,?,?,?,?,?,?,?)",
        (
            encode_u64(sequence),
            encoded_id,
            200 + sequence,
            accepted_at,
            author,
            f"title {sequence}",
            f"body {sequence}".encode(),
            b"old hash",
        ),
    )


def test_migration_one_definition_is_unchanged():
    digest = hashlib.sha256("\0".join(MIGRATIONS[1]).encode()).hexdigest()
    assert digest == MIGRATION_1_DIGEST


def test_fresh_database_runs_ordered_migrations_to_latest(tmp_path):
    database = Database(tmp_path / "node.db")
    database.initialize()
    assert database.get_schema_version() == LATEST_SCHEMA_VERSION == 5
    with database.connect() as connection:
        assert schema_names(connection) - {"sqlite_sequence"} == V5_TABLES


def test_initialize_is_idempotent_and_preserves_rows(tmp_path):
    database = Database(tmp_path / "node.db")
    database.initialize()
    MessageStore(database).store_message(
        created_at=1, author="SRC", recipient="BOX", body="kept"
    )
    database.initialize()
    assert (
        MessageStore(database)
        .get_new_messages(callsign="BOX", since=0, limit=1)
        .messages[0]
        .body
        == "kept"
    )


def test_database_can_be_reopened_and_initialized(tmp_path):
    path = tmp_path / "node.db"
    Database(path).initialize()
    reopened = Database(path)
    reopened.initialize()
    assert reopened.get_schema_version() == 5


def test_unsupported_future_schema_is_rejected(tmp_path):
    database = Database(tmp_path / "future.db")
    with database.connect() as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(UnsupportedSchemaVersionError, match="99.*newer"):
        database.initialize()


def test_connections_enable_required_durability_pragmas(tmp_path):
    database = Database(tmp_path / "node.db")
    with database.connect() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2


def test_message_and_bulletin_sequence_state_are_independent(tmp_path):
    database = Database(tmp_path / "node.db")
    database.initialize()
    messages = MessageStore(database)
    bulletins = BulletinStore(database)
    assert (
        messages.store_message(created_at=1, author="A", recipient="BOX", body="m") == 1
    )
    assert (
        messages.store_message(created_at=2, author="A", recipient="BOX", body="m") == 2
    )
    assert bulletins.store_bulletin(created_at=1, author="A", title="b", body="b") == 1
    with database.connect() as connection:
        assert (
            connection.execute("SELECT last_value FROM mailbox_sequences").fetchone()[0]
            == 2
        )
        assert (
            connection.execute("SELECT last_value FROM bulletin_sequence").fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO messages VALUES ('BOX',0,1,1,1,'A',X'00')",
        "INSERT INTO messages VALUES ('BOX',4294967296,1,1,1,'A',X'00')",
        "INSERT INTO messages VALUES ('BOX',1,1,-1,1,'A',X'00')",
        "INSERT INTO messages VALUES ('BOX',1,1,4294967296,1,'A',X'00')",
        "INSERT INTO mailbox_sequences VALUES ('BOX',-1)",
        "INSERT INTO mailbox_sequences VALUES ('BOX',4294967296)",
        "INSERT INTO bulletins VALUES (0,1,1,'A','T',X'00')",
        "INSERT INTO bulletins VALUES (4294967296,1,1,'A','T',X'00')",
        "INSERT INTO bulletins VALUES (1,-1,1,'A','T',X'00')",
        "INSERT INTO bulletins VALUES (1,4294967296,1,'A','T',X'00')",
        "INSERT INTO bulletin_sequence VALUES (2,0)",
    ],
)
def test_v2_range_and_singleton_constraints(tmp_path, sql):
    database = Database(tmp_path / "node.db")
    database.initialize()
    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(sql)


def test_message_identity_is_recipient_and_sequence(tmp_path):
    database = Database(tmp_path / "node.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO messages VALUES ('A',1,1,1,1,'SRC',X'00')")
        connection.execute("INSERT INTO messages VALUES ('B',1,2,1,1,'SRC',X'00')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO messages VALUES ('A',1,3,1,1,'SRC',X'00')")


def test_empty_v1_database_migrates_and_restarts(tmp_path):
    path = tmp_path / "old.db"
    create_v1(path).close()
    database = Database(path)
    database.initialize()
    Database(path).initialize()
    assert database.get_schema_version() == 5
    with database.connect() as connection:
        assert schema_names(connection) - {"sqlite_sequence"} == V5_TABLES


def test_interleaved_v1_messages_are_resequenced_per_mailbox_with_all_content(tmp_path):
    path = tmp_path / "old.db"
    connection = create_v1(path)
    add_v1_message(connection, 1, 11, "EA3GNU", author="A", accepted_at=501)
    add_v1_message(connection, 2, 12, "EA1ABC", author="B", accepted_at=502)
    add_v1_message(connection, 3, 13, "EA3GNU", author="C", accepted_at=503)
    add_v1_message(connection, 4, 14, "EA1ABC", author="D", accepted_at=504)
    connection.close()
    database = Database(path)
    database.initialize()
    with database.connect() as connection:
        rows = [
            tuple(row)
            for row in connection.execute(
                """SELECT recipient,mailbox_sequence,author,created_at,accepted_at,body
               FROM messages ORDER BY recipient,mailbox_sequence"""
            )
        ]
        state = dict(
            connection.execute("SELECT recipient,last_value FROM mailbox_sequences")
        )
        api_order = [
            tuple(row)
            for row in connection.execute(
                "SELECT api_sequence,recipient,mailbox_sequence FROM messages ORDER BY api_sequence"
            )
        ]
        api_high_water = connection.execute(
            "SELECT last_value FROM api_message_sequence WHERE singleton=1"
        ).fetchone()[0]
    assert rows == [
        ("EA1ABC", 1, "B", 102, 502, b"message 2"),
        ("EA1ABC", 2, "D", 104, 504, b"message 4"),
        ("EA3GNU", 1, "A", 101, 501, b"message 1"),
        ("EA3GNU", 2, "C", 103, 503, b"message 3"),
    ]
    assert state == {"EA1ABC": 2, "EA3GNU": 2}
    assert api_order == [
        (1, "EA3GNU", 1),
        (2, "EA1ABC", 1),
        (3, "EA3GNU", 2),
        (4, "EA1ABC", 2),
    ]
    assert api_high_water == 4


def test_one_mailbox_migrates_and_next_message_continues(tmp_path):
    path = tmp_path / "old.db"
    connection = create_v1(path)
    add_v1_message(connection, 7, 1, "BOX")
    add_v1_message(connection, 9, 2, "BOX")
    connection.close()
    database = Database(path)
    database.initialize()
    assert (
        MessageStore(database).store_message(
            created_at=1, author="A", recipient="BOX", body="next"
        )
        == 3
    )


def test_v3_to_v4_backfills_deterministic_api_order_and_continues(tmp_path):
    path = tmp_path / "v3.db"
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    migrate(connection, 0, target_version=3)
    connection.execute("INSERT INTO mailbox_sequences VALUES ('EA3GNU', 1)")
    connection.execute("INSERT INTO mailbox_sequences VALUES ('EA3ABC', 1)")
    connection.execute("INSERT INTO messages VALUES ('EA3GNU',1,10,500,'SRC',X'61')")
    connection.execute("INSERT INTO messages VALUES ('EA3ABC',1,10,500,'SRC',X'62')")
    connection.close()

    database = Database(path)
    database.initialize()
    with database.connect() as connection:
        rows = [
            tuple(row)
            for row in connection.execute(
                "SELECT api_sequence,recipient,body FROM messages ORDER BY api_sequence"
            )
        ]
        high_water = connection.execute(
            "SELECT last_value FROM api_message_sequence"
        ).fetchone()[0]
    assert rows == [(1, "EA3ABC", b"b"), (2, "EA3GNU", b"a")]
    assert high_water == 2

    MessageStore(database).store_message(
        created_at=11, author="SRC", recipient="EA3GNU", body="next"
    )
    assert MessageStore(database).api_high_water() == 3


def test_v1_bulletins_preserve_order_and_all_content_then_continue(tmp_path):
    path = tmp_path / "old.db"
    connection = create_v1(path)
    add_v1_bulletin(connection, 8, 21, author="A", accepted_at=608)
    add_v1_bulletin(connection, 20, 22, author="B", accepted_at=620)
    connection.close()
    database = Database(path)
    database.initialize()
    with database.connect() as connection:
        rows = [
            tuple(row)
            for row in connection.execute(
                "SELECT sequence,author,created_at,accepted_at,title,body FROM bulletins ORDER BY sequence"
            )
        ]
    assert rows == [
        (1, "A", 208, 608, "title 8", b"body 8"),
        (2, "B", 220, 620, "title 20", b"body 20"),
    ]
    assert (
        BulletinStore(database).store_bulletin(
            created_at=1, author="C", title="next", body="next"
        )
        == 3
    )


def test_successful_migration_removes_every_obsolete_table_and_column(tmp_path):
    path = tmp_path / "old.db"
    create_v1(path).close()
    database = Database(path)
    database.initialize()
    with database.connect() as connection:
        tables = schema_names(connection)
        message_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(messages)")
        }
        bulletin_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(bulletins)")
        }
    assert not ({"objects", "sequences", "messages_v1", "bulletins_v1"} & tables)
    assert not ({"message_id", "content_hash"} & message_columns)
    assert not ({"bulletin_id", "content_hash"} & bulletin_columns)


def test_v2_migration_failure_leaves_complete_usable_v1_schema(tmp_path):
    path = tmp_path / "old.db"
    connection = create_v1(path)
    add_v1_message(connection, 1, 1, "BOX", accepted_at=123)
    broken = {1: MIGRATIONS[1], 2: (MIGRATIONS[2][0], "NOT VALID SQL")}
    with pytest.raises(sqlite3.OperationalError):
        migrate(connection, 1, target_version=2, migrations=broken)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    assert {"objects", "sequences", "messages", "bulletins"} <= schema_names(connection)
    assert "messages_v1" not in schema_names(connection)
    assert connection.execute("SELECT accepted_at FROM messages").fetchone()[0] == 123
    connection.close()


def test_generic_migration_failure_rolls_back_schema_and_version():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    with pytest.raises(sqlite3.OperationalError):
        migrate(
            connection,
            0,
            target_version=1,
            migrations={1: ("CREATE TABLE temporary(value)", "NOT SQL")},
        )
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
    assert "temporary" not in schema_names(connection)
