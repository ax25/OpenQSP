import sqlite3
import pytest
from openqsp.storage import *


def test_full_lifecycle_independent_sequences(database):
    m = MessageStore(database)
    b = BulletinStore(database)
    assert (
        m.store_message(
            created_at=1, author="EA1AAA", recipient="EA2AAA", body="a"
        ).sequence
        == 1
    )
    assert (
        b.store_bulletin(created_at=1, author="EA1AAA", title="t", body="b").sequence
        == 1
    )
    assert (
        m.store_message(
            created_at=2, author="EA1AAA", recipient="EA3AAA", body="c"
        ).sequence
        == 1
    )
    assert (
        m.get_new_messages(callsign="EA2AAA", since=0, limit=20).messages[0].body == "a"
    )
    assert b.get_bulletin(sequence=1).body == "b"


def test_interleaved_restart(database):
    m = MessageStore(database)
    b = BulletinStore(database)
    for i in range(3):
        m.store_message(
            created_at=i + 1, author="EA1AAA", recipient="EA2AAA", body=str(i)
        )
        b.store_bulletin(created_at=i + 1, author="EA1AAA", title=str(i), body=str(i))
    assert (
        MessageStore(database)
        .store_message(created_at=4, author="EA1AAA", recipient="EA2AAA", body="3")
        .sequence
        == 4
    )
    assert (
        BulletinStore(database)
        .store_bulletin(created_at=4, author="EA1AAA", title="3", body="3")
        .sequence
        == 4
    )


def test_failed_insert_has_no_gap(database):
    m = MessageStore(database)
    with database.connect() as c:
        c.execute(
            "CREATE TRIGGER reject BEFORE INSERT ON messages WHEN NEW.body=X'626164' BEGIN SELECT RAISE(ABORT,'bad'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        m.store_message(created_at=1, author="EA1AAA", recipient="EA2AAA", body="bad")
    assert (
        m.store_message(
            created_at=2, author="EA1AAA", recipient="EA2AAA", body="ok"
        ).sequence
        == 1
    )


def test_durable_configuration(database):
    with database.connect() as c:
        assert (
            c.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
            and c.execute("PRAGMA synchronous").fetchone()[0] == 2
        )
