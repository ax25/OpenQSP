"""Cross-store lifecycle and integrity scenarios."""

import sqlite3

import pytest

from openqsp.storage import BulletinStore, Database, MessageStore, StorageIntegrityError


def stores(path, accepted_at=1_000):
    database = Database(path)
    database.initialize()
    return (
        database,
        MessageStore(database, clock=lambda: accepted_at),
        BulletinStore(database, clock=lambda: accepted_at),
    )


def test_full_restart_lifecycle_preserves_both_streams(tmp_path):
    path = tmp_path / "node.db"
    _, messages, bulletins = stores(path)
    assert (
        messages.store_message(created_at=1, author="SRC", recipient="A", body="m1")
        == 1
    )
    assert (
        bulletins.store_bulletin(created_at=1, author="SRC", title="b1", body="body")
        == 1
    )
    assert (
        messages.store_message(created_at=2, author="SRC", recipient="A", body="m2")
        == 2
    )

    _, messages, bulletins = stores(path, accepted_at=2_000)
    page = messages.get_new_messages(callsign="A", since=0, limit=20)
    assert [item.body for item in page.messages] == ["m1", "m2"]
    assert [item.accepted_at for item in page.messages] == [1_000, 1_000]
    assert bulletins.get_bulletin(sequence=1).accepted_at == 1_000
    assert (
        messages.store_message(created_at=3, author="SRC", recipient="A", body="m3")
        == 3
    )
    assert (
        bulletins.store_bulletin(created_at=2, author="SRC", title="b2", body="body")
        == 2
    )


def test_interleaved_mailboxes_and_bulletins_have_independent_sequences(tmp_path):
    _, messages, bulletins = stores(tmp_path / "node.db")
    results = [
        messages.store_message(created_at=1, author="A", recipient="X", body="x"),
        bulletins.store_bulletin(created_at=1, author="A", title="one", body="b"),
        messages.store_message(created_at=2, author="A", recipient="Y", body="y"),
        bulletins.store_bulletin(created_at=2, author="A", title="two", body="b"),
        messages.store_message(created_at=3, author="A", recipient="X", body="x2"),
    ]
    assert results == [1, 1, 1, 2, 2]


def test_message_failure_does_not_affect_bulletin_state(tmp_path):
    database, messages, bulletins = stores(tmp_path / "node.db")
    with database.connect() as connection:
        connection.execute(
            """CREATE TRIGGER reject_message BEFORE INSERT ON messages
               BEGIN SELECT RAISE(ABORT, 'reject'); END"""
        )
    with pytest.raises(sqlite3.IntegrityError):
        messages.store_message(created_at=1, author="A", recipient="X", body="x")
    assert (
        bulletins.store_bulletin(
            created_at=1, author="A", title="still works", body="b"
        )
        == 1
    )


def test_bulletin_failure_does_not_affect_mailbox_state(tmp_path):
    database, messages, bulletins = stores(tmp_path / "node.db")
    with database.connect() as connection:
        connection.execute(
            """CREATE TRIGGER reject_bulletin BEFORE INSERT ON bulletins
               BEGIN SELECT RAISE(ABORT, 'reject'); END"""
        )
    with pytest.raises(sqlite3.IntegrityError):
        bulletins.store_bulletin(created_at=1, author="A", title="x", body="x")
    assert (
        messages.store_message(created_at=1, author="A", recipient="X", body="works")
        == 1
    )


def test_missing_bulletin_sequence_state_is_integrity_error(tmp_path):
    database, _, bulletins = stores(tmp_path / "node.db")
    with database.connect() as connection:
        connection.execute("DELETE FROM bulletin_sequence")
    with pytest.raises(StorageIntegrityError, match="missing"):
        bulletins.get_new_bulletins(since=0, limit=1)
    with pytest.raises(StorageIntegrityError, match="missing"):
        bulletins.store_bulletin(created_at=1, author="A", title="x", body="x")


def test_database_integrity_check_passes_after_normal_lifecycle(tmp_path):
    database, messages, bulletins = stores(tmp_path / "node.db")
    for number in range(5):
        messages.store_message(
            created_at=number, author="A", recipient=str(number % 2), body="m"
        )
        bulletins.store_bulletin(
            created_at=number, author="A", title=str(number), body="b"
        )
    with database.connect() as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
