"""Cross-store lifecycle and integrity coverage."""

import sqlite3
import pytest
from openqsp.storage import BulletinStore, Database, MessageStore, StorageIntegrityError


def test_full_restart_lifecycle(tmp_path):
    path = tmp_path / "db"
    db = Database(path)
    db.initialize()
    m = MessageStore(db, clock=lambda: 1000)
    b = BulletinStore(db, clock=lambda: 2000)
    assert [
        m.store_message(created_at=i, author="SRC", recipient="BOX", body=str(i))
        for i in (1, 2)
    ] == [1, 2]
    assert [
        b.store_bulletin(created_at=i, author="SRC", title=str(i), body="b")
        for i in (1, 2)
    ] == [1, 2]
    m = MessageStore(Database(path))
    b = BulletinStore(Database(path))
    assert [
        x.accepted_at
        for x in m.get_new_messages(callsign="BOX", since=0, limit=20).messages
    ] == [1000, 1000]
    assert b.get_bulletin(sequence=2).accepted_at == 2000


def test_failed_insert_rolls_back_sequence(tmp_path):
    db = Database(tmp_path / "db")
    db.initialize()
    m = MessageStore(db)
    with db.connect() as c:
        c.execute(
            """CREATE TRIGGER fail BEFORE INSERT ON messages BEGIN SELECT RAISE(ABORT,'forced'); END"""
        )
    with pytest.raises(sqlite3.IntegrityError):
        m.store_message(created_at=1, author="A", recipient="B", body="x")
    with db.connect() as c:
        assert c.execute("SELECT count(*) FROM mailbox_sequences").fetchone()[0] == 0
        c.execute("DROP TRIGGER fail")
    assert m.store_message(created_at=1, author="A", recipient="B", body="x") == 1


def test_corrupt_sequence_state_is_detected(tmp_path):
    db = Database(tmp_path / "db")
    db.initialize()
    m = MessageStore(db)
    with db.connect() as c:
        c.execute("PRAGMA ignore_check_constraints=ON")
        c.execute("INSERT INTO mailbox_sequences VALUES ('B',-1)")
    with pytest.raises(StorageIntegrityError):
        m.get_new_messages(callsign="B", since=0, limit=1)
