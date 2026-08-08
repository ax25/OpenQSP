import sqlite3
import pytest
from openqsp.storage import *
from openqsp.storage.database import UnsupportedSchemaVersionError
from openqsp.storage.migrations import migrate, encode_u64


def test_new_schema_and_idempotent_restart(tmp_path):
    p = tmp_path / "x.db"
    d = Database(p)
    d.initialize()
    d.initialize()
    assert d.get_schema_version() == 2
    with d.connect() as c:
        names = {
            x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {
        "messages",
        "mailbox_sequences",
        "bulletins",
        "bulletin_sequence",
    } <= names and "objects" not in names


def test_newer_schema_rejected(tmp_path):
    p = tmp_path / "x.db"
    c = sqlite3.connect(p)
    c.execute("PRAGMA user_version=99")
    c.close()
    with pytest.raises(UnsupportedSchemaVersionError):
        Database(p).initialize()


def test_connection_pragmas(database):
    with database.connect() as c:
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert c.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert c.execute("PRAGMA synchronous").fetchone()[0] == 2


def make_v1(path, messages=(), bulletins=()):
    c = sqlite3.connect(path, isolation_level=None)
    migrate(c, 0, target_version=1)
    for oid, seq, created, accepted, author, recipient, body in messages:
        eid = encode_u64(oid)
        c.execute("INSERT INTO objects VALUES(?,'message')", (eid,))
        c.execute(
            "INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)",
            (
                encode_u64(seq),
                eid,
                created,
                accepted,
                author,
                recipient,
                body.encode(),
                b"h",
            ),
        )
    for oid, seq, created, accepted, author, title, body in bulletins:
        eid = encode_u64(oid)
        c.execute("INSERT INTO objects VALUES(?,'bulletin')", (eid,))
        c.execute(
            "INSERT INTO bulletins VALUES(?,?,?,?,?,?,?,?)",
            (
                encode_u64(seq),
                eid,
                created,
                accepted,
                author,
                title,
                body.encode(),
                b"h",
            ),
        )
    c.close()


def test_empty_v1_migration(tmp_path):
    p = tmp_path / "x.db"
    make_v1(p)
    d = Database(p)
    d.initialize()
    assert d.get_schema_version() == 2
    assert (
        MessageStore(d)
        .store_message(created_at=1, author="EA1AAA", recipient="EA2AAA", body="x")
        .sequence
        == 1
    )


def test_realistic_v1_migration_preserves_content_and_resequences(tmp_path):
    p = tmp_path / "x.db"
    make_v1(
        p,
        [
            (90, 1, 11, 21, "EA1AAA", "EA2AAA", "a"),
            (80, 2, 12, 22, "EA1BBB", "EA3AAA", "b"),
            (70, 3, 13, 23, "EA1CCC", "EA2AAA", "c"),
        ],
        [
            (60, 4, 14, 24, "EA1AAA", "one", "body1"),
            (50, 7, 15, 25, "EA1BBB", "two", "body2"),
        ],
    )
    d = Database(p)
    d.initialize()
    a = MessageStore(d).get_new_messages(callsign="EA2AAA", since=0, limit=20).messages
    b = MessageStore(d).get_new_messages(callsign="EA3AAA", since=0, limit=20).messages
    assert [(x.sequence, x.created_at, x.author, x.body) for x in a] == [
        (1, 11, "EA1AAA", "a"),
        (2, 13, "EA1CCC", "c"),
    ]
    assert [(x.sequence, x.body) for x in b] == [(1, "b")]
    bs = BulletinStore(d)
    assert bs.get_bulletin(sequence=1) == StoredBulletin(
        1, 14, "EA1AAA", "one", "body1"
    )
    assert bs.get_bulletin(sequence=2).title == "two"
    assert (
        MessageStore(d)
        .store_message(created_at=16, author="EA1AAA", recipient="EA2AAA", body="d")
        .sequence
        == 3
    )
    assert (
        bs.store_bulletin(
            created_at=16, author="EA1AAA", title="three", body="body3"
        ).sequence
        == 3
    )
    Database(p).initialize()
    assert (
        MessageStore(Database(p))
        .get_new_messages(callsign="EA2AAA", since=0, limit=20)
        .messages[-1]
        .body
        == "d"
    )


def test_migration_failure_rolls_back(tmp_path):
    p = tmp_path / "x.db"
    make_v1(p)
    c = sqlite3.connect(p, isolation_level=None)
    with pytest.raises(RuntimeError):
        migrate(c, 1, target_version=2, migrations={})
    assert c.execute("PRAGMA user_version").fetchone()[0] == 1
    c.close()
