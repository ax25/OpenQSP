"""Ordered SQLite schema migrations."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence

LATEST_SCHEMA_VERSION = 3

# OpenQSP object IDs and synchronization sequences are unsigned 64-bit values,
# while SQLite INTEGER is signed. Both are stored as exactly eight big-endian
# bytes. SQLite compares equal-length BLOBs lexicographically, so this encoding
# also preserves unsigned ordering for future ``sequence > since`` queries.
_MIGRATION_1 = (
    """
    CREATE TABLE objects (
        object_id BLOB PRIMARY KEY
            CHECK(typeof(object_id) = 'blob' AND length(object_id) = 8),
        object_type TEXT NOT NULL
            CHECK(object_type IN ('message', 'bulletin'))
    )
    """,
    """
    CREATE TABLE sequences (
        stream TEXT PRIMARY KEY CHECK(stream IN ('messages', 'bulletins')),
        last_value BLOB NOT NULL
            CHECK(typeof(last_value) = 'blob' AND length(last_value) = 8)
    )
    """,
    """
    INSERT INTO sequences(stream, last_value) VALUES
        ('messages', X'0000000000000000'),
        ('bulletins', X'0000000000000000')
    """,
    """
    CREATE TABLE messages (
        sequence BLOB NOT NULL UNIQUE
            CHECK(typeof(sequence) = 'blob' AND length(sequence) = 8
                  AND sequence > X'0000000000000000'),
        message_id BLOB PRIMARY KEY
            CHECK(typeof(message_id) = 'blob' AND length(message_id) = 8),
        created_at INTEGER NOT NULL CHECK(created_at >= 0),
        accepted_at INTEGER NOT NULL CHECK(accepted_at >= 0),
        author TEXT NOT NULL,
        recipient TEXT NOT NULL,
        body BLOB NOT NULL,
        content_hash BLOB NOT NULL,
        FOREIGN KEY(message_id) REFERENCES objects(object_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE bulletins (
        sequence BLOB NOT NULL UNIQUE
            CHECK(typeof(sequence) = 'blob' AND length(sequence) = 8
                  AND sequence > X'0000000000000000'),
        bulletin_id BLOB PRIMARY KEY
            CHECK(typeof(bulletin_id) = 'blob' AND length(bulletin_id) = 8),
        created_at INTEGER NOT NULL CHECK(created_at >= 0),
        accepted_at INTEGER NOT NULL CHECK(accepted_at >= 0),
        author TEXT NOT NULL,
        title TEXT NOT NULL,
        body BLOB NOT NULL,
        content_hash BLOB NOT NULL,
        FOREIGN KEY(bulletin_id) REFERENCES objects(object_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX idx_messages_author_sequence ON messages(author, sequence)",
    "CREATE INDEX idx_messages_recipient_sequence ON messages(recipient, sequence)",
    """
    CREATE TRIGGER messages_object_type_insert
    BEFORE INSERT ON messages
    WHEN (SELECT object_type FROM objects WHERE object_id = NEW.message_id)
         IS NOT 'message'
    BEGIN
        SELECT RAISE(ABORT, 'message_id must reference a message object');
    END
    """,
    """
    CREATE TRIGGER messages_object_type_update
    BEFORE UPDATE OF message_id ON messages
    WHEN (SELECT object_type FROM objects WHERE object_id = NEW.message_id)
         IS NOT 'message'
    BEGIN
        SELECT RAISE(ABORT, 'message_id must reference a message object');
    END
    """,
    """
    CREATE TRIGGER bulletins_object_type_insert
    BEFORE INSERT ON bulletins
    WHEN (SELECT object_type FROM objects WHERE object_id = NEW.bulletin_id)
         IS NOT 'bulletin'
    BEGIN
        SELECT RAISE(ABORT, 'bulletin_id must reference a bulletin object');
    END
    """,
    """
    CREATE TRIGGER bulletins_object_type_update
    BEFORE UPDATE OF bulletin_id ON bulletins
    WHEN (SELECT object_type FROM objects WHERE object_id = NEW.bulletin_id)
         IS NOT 'bulletin'
    BEGIN
        SELECT RAISE(ABORT, 'bulletin_id must reference a bulletin object');
    END
    """,
    """
    CREATE TRIGGER objects_type_is_immutable
    BEFORE UPDATE OF object_type ON objects
    WHEN OLD.object_type != NEW.object_type
    BEGIN
        SELECT RAISE(ABORT, 'an object type cannot be changed');
    END
    """,
    """
    CREATE TRIGGER sequences_do_not_move_backwards
    BEFORE UPDATE OF last_value ON sequences
    WHEN NEW.last_value < OLD.last_value
    BEGIN
        SELECT RAISE(ABORT, 'a sequence cannot move backwards');
    END
    """,
)

_MIGRATION_2 = (
    "ALTER TABLE messages RENAME TO messages_v1",
    "ALTER TABLE bulletins RENAME TO bulletins_v1",
    """
    CREATE TABLE mailbox_sequences (
        recipient TEXT PRIMARY KEY,
        last_value INTEGER NOT NULL
            CHECK(typeof(last_value) = 'integer' AND last_value BETWEEN 0 AND 4294967295)
    )
    """,
    """
    CREATE TABLE messages (
        recipient TEXT NOT NULL,
        mailbox_sequence INTEGER NOT NULL
            CHECK(typeof(mailbox_sequence) = 'integer' AND mailbox_sequence BETWEEN 1 AND 4294967295),
        created_at INTEGER NOT NULL
            CHECK(typeof(created_at) = 'integer' AND created_at BETWEEN 0 AND 4294967295),
        accepted_at INTEGER NOT NULL
            CHECK(typeof(accepted_at) = 'integer' AND accepted_at >= 0),
        author TEXT NOT NULL,
        body BLOB NOT NULL,
        PRIMARY KEY(recipient, mailbox_sequence)
    ) WITHOUT ROWID
    """,
    """
    INSERT INTO messages(recipient, mailbox_sequence, created_at, accepted_at, author, body)
    SELECT recipient,
           ROW_NUMBER() OVER (PARTITION BY recipient ORDER BY sequence, message_id),
           created_at, accepted_at, author, body
      FROM messages_v1
     ORDER BY sequence, message_id
    """,
    """
    INSERT INTO mailbox_sequences(recipient, last_value)
    SELECT recipient, MAX(mailbox_sequence) FROM messages GROUP BY recipient
    """,
    """
    CREATE TABLE bulletin_sequence (
        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
        last_value INTEGER NOT NULL
            CHECK(typeof(last_value) = 'integer' AND last_value BETWEEN 0 AND 4294967295)
    )
    """,
    "INSERT INTO bulletin_sequence(singleton, last_value) VALUES (1, 0)",
    """
    CREATE TABLE bulletins (
        sequence INTEGER PRIMARY KEY
            CHECK(typeof(sequence) = 'integer' AND sequence BETWEEN 1 AND 4294967295),
        created_at INTEGER NOT NULL
            CHECK(typeof(created_at) = 'integer' AND created_at BETWEEN 0 AND 4294967295),
        accepted_at INTEGER NOT NULL
            CHECK(typeof(accepted_at) = 'integer' AND accepted_at >= 0),
        author TEXT NOT NULL,
        title TEXT NOT NULL,
        body BLOB NOT NULL
    )
    """,
    """
    INSERT INTO bulletins(sequence, created_at, accepted_at, author, title, body)
    SELECT ROW_NUMBER() OVER (ORDER BY sequence, bulletin_id),
           created_at, accepted_at, author, title, body
      FROM bulletins_v1
     ORDER BY sequence, bulletin_id
    """,
    "UPDATE bulletin_sequence SET last_value = (SELECT COUNT(*) FROM bulletins)",
    "DROP TABLE messages_v1",
    "DROP TABLE bulletins_v1",
    "DROP TABLE objects",
    "DROP TABLE sequences",
)

_MIGRATION_3 = (
    """
    CREATE TABLE accounts (
        callsign TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        created_at INTEGER NOT NULL
            CHECK(typeof(created_at) = 'integer' AND created_at >= 0)
    ) WITHOUT ROWID
    """,
)

MIGRATIONS: Mapping[int, Sequence[str]] = {
    1: _MIGRATION_1,
    2: _MIGRATION_2,
    3: _MIGRATION_3,
}


def migrate(
    connection: sqlite3.Connection,
    current_version: int,
    *,
    target_version: int = LATEST_SCHEMA_VERSION,
    migrations: Mapping[int, Sequence[str]] = MIGRATIONS,
) -> None:
    """Apply ordered migrations atomically, including their version markers."""
    if current_version < 0 or current_version > target_version:
        raise ValueError("current schema version is outside the migration range")

    connection.execute("BEGIN IMMEDIATE")
    try:
        for version in range(current_version + 1, target_version + 1):
            try:
                statements = migrations[version]
            except KeyError as error:
                raise RuntimeError(f"missing schema migration {version}") from error
            for statement in statements:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def encode_u64(value: int) -> bytes:
    """Encode an OpenQSP unsigned 64-bit value for a BLOB column."""
    if not 0 <= value <= 0xFFFF_FFFF_FFFF_FFFF:
        raise ValueError("value is outside the unsigned 64-bit range")
    return value.to_bytes(8, "big")


def decode_u64(value: bytes) -> int:
    """Decode an eight-byte database representation into an integer."""
    if len(value) != 8:
        raise ValueError("u64 database value must contain exactly 8 bytes")
    return int.from_bytes(value, "big")
