import sqlite3
import pytest

from openqsp.storage import Database, UnsupportedSchemaVersionError
from openqsp.storage.migrations import (
    LATEST_SCHEMA_VERSION,
    MIGRATIONS,
    encode_u64,
    migrate,
)

EXPECTED = {"messages", "mailbox_sequences", "bulletins", "bulletin_sequence"}


def names(c, kind="table"):
    return {
        r[0] for r in c.execute("SELECT name FROM sqlite_schema WHERE type=?", (kind,))
    }


def v1(path):
    c = sqlite3.connect(path, isolation_level=None)
    c.execute("PRAGMA foreign_keys=ON")
    migrate(c, 0, target_version=1)
    return c


def add_v1_message(c, seq, mid, recipient, accepted):
    oid = encode_u64(mid)
    c.execute("INSERT INTO objects VALUES (?, 'message')", (oid,))
    c.execute(
        "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)",
        (
            encode_u64(seq),
            oid,
            seq,
            accepted,
            "SRC",
            recipient,
            f"m{seq}".encode(),
            b"hash",
        ),
    )


def add_v1_bulletin(c, seq, bid, accepted):
    oid = encode_u64(bid)
    c.execute("INSERT INTO objects VALUES (?, 'bulletin')", (oid,))
    c.execute(
        "INSERT INTO bulletins VALUES (?,?,?,?,?,?,?,?)",
        (
            encode_u64(seq),
            oid,
            seq,
            accepted,
            "SRC",
            f"t{seq}",
            f"b{seq}".encode(),
            b"hash",
        ),
    )


def test_fresh_database_effective_v2_schema(tmp_path):
    db = Database(tmp_path / "db")
    db.initialize()
    assert db.get_schema_version() == LATEST_SCHEMA_VERSION == 2
    with db.connect() as c:
        assert names(c) - {"sqlite_sequence"} == EXPECTED
        message_cols = {r[1] for r in c.execute("PRAGMA table_info(messages)")}
        bulletin_cols = {r[1] for r in c.execute("PRAGMA table_info(bulletins)")}
    assert message_cols == {
        "recipient",
        "mailbox_sequence",
        "created_at",
        "accepted_at",
        "author",
        "body",
    }
    assert bulletin_cols == {
        "sequence",
        "created_at",
        "accepted_at",
        "author",
        "title",
        "body",
    }


def test_v1_migration_resequences_and_preserves_content(tmp_path):
    path = tmp_path / "old"
    c = v1(path)
    for args in [
        (1, 11, "GNU", 101),
        (2, 12, "ABC", 102),
        (3, 13, "GNU", 103),
        (4, 14, "ABC", 104),
    ]:
        add_v1_message(c, *args)
    add_v1_bulletin(c, 9, 21, 209)
    add_v1_bulletin(c, 20, 22, 220)
    c.close()
    db = Database(path)
    db.initialize()
    with db.connect() as c:
        messages = [
            tuple(r)
            for r in c.execute(
                "SELECT recipient,mailbox_sequence,created_at,accepted_at,body FROM messages ORDER BY recipient,mailbox_sequence"
            )
        ]
        bulletins = [
            tuple(r)
            for r in c.execute(
                "SELECT sequence,created_at,accepted_at,title,body FROM bulletins ORDER BY sequence"
            )
        ]
        state = dict(c.execute("SELECT recipient,last_value FROM mailbox_sequences"))
        tables = names(c)
    assert messages == [
        ("ABC", 1, 2, 102, b"m2"),
        ("ABC", 2, 4, 104, b"m4"),
        ("GNU", 1, 1, 101, b"m1"),
        ("GNU", 2, 3, 103, b"m3"),
    ]
    assert bulletins == [(1, 9, 209, "t9", b"b9"), (2, 20, 220, "t20", b"b20")]
    assert state == {"ABC": 2, "GNU": 2}
    assert not ({"objects", "sequences", "messages_v1", "bulletins_v1"} & tables)


def test_v2_migration_failure_leaves_v1_intact(tmp_path):
    path = tmp_path / "old"
    c = v1(path)
    add_v1_message(c, 1, 1, "BOX", 123)
    broken = {1: MIGRATIONS[1], 2: (MIGRATIONS[2][0], "NOT SQL")}
    with pytest.raises(sqlite3.OperationalError):
        migrate(c, 1, target_version=2, migrations=broken)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 1
    assert "messages" in names(c) and "messages_v1" not in names(c)
    assert c.execute("SELECT accepted_at FROM messages").fetchone()[0] == 123
    c.close()


def test_generic_migration_failure_is_atomic():
    c = sqlite3.connect(":memory:", isolation_level=None)
    with pytest.raises(sqlite3.OperationalError):
        migrate(c, 0, target_version=1, migrations={1: ("CREATE TABLE x(a)", "NO SQL")})
    assert c.execute("PRAGMA user_version").fetchone()[0] == 0 and "x" not in names(c)


def test_initialize_is_idempotent_and_future_rejected(tmp_path):
    db = Database(tmp_path / "db")
    db.initialize()
    db.initialize()
    assert db.get_schema_version() == 2
    future = Database(tmp_path / "future")
    with future.connect() as c:
        c.execute("PRAGMA user_version=99")
    with pytest.raises(UnsupportedSchemaVersionError):
        future.initialize()


def test_schema_constraints_enforce_u32_and_identity(tmp_path):
    db = Database(tmp_path / "db")
    db.initialize()
    with db.connect() as c:
        for sql in [
            "INSERT INTO mailbox_sequences VALUES ('X',-1)",
            "INSERT INTO bulletin_sequence VALUES (2,0)",
        ]:
            with pytest.raises(sqlite3.IntegrityError):
                c.execute(sql)
        c.execute("INSERT INTO messages VALUES ('X',1,0,0,'A',X'00')")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO messages VALUES ('X',1,0,0,'A',X'00')")
