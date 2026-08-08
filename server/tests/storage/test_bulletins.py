"""Tests for atomic bulletin persistence and allocation."""

import sqlite3

import pytest

from openqsp.storage import BulletinStore, Database, SequenceExhaustedError


def create_store(path, *, clock=lambda: 700):
    database = Database(path)
    database.initialize()
    return database, BulletinStore(database, clock=clock)


def bulletin(**changes):
    values = {
        "created_at": 123,
        "author": "EA1ABC",
        "title": "Café ☕",
        "body": "Bulletin body 🌍",
    }
    values.update(changes)
    return values


def test_store_bulletin_persists_complete_row_and_returns_sequence(tmp_path):
    database, store = create_store(tmp_path / "node.db", clock=lambda: 456)
    assert store.store_bulletin(**bulletin()) == 1
    with database.connect() as connection:
        row = connection.execute(
            "SELECT sequence,author,created_at,accepted_at,title,body FROM bulletins"
        ).fetchone()
    assert tuple(row) == (1, "EA1ABC", 123, 456, "Café ☕", "Bulletin body 🌍".encode())


def test_first_and_second_bulletins_receive_one_and_two(tmp_path):
    _, store = create_store(tmp_path / "node.db")
    assert store.store_bulletin(**bulletin(title="first")) == 1
    assert store.store_bulletin(**bulletin(title="second")) == 2


def test_bulletin_sequence_survives_restart(tmp_path):
    path = tmp_path / "node.db"
    _, store = create_store(path)
    assert store.store_bulletin(**bulletin()) == 1
    assert BulletinStore(Database(path)).store_bulletin(**bulletin(title="next")) == 2


def test_failed_insert_does_not_advance_bulletin_sequence(tmp_path):
    database, store = create_store(tmp_path / "node.db")
    with database.connect() as connection:
        connection.execute(
            """CREATE TRIGGER force_bulletin_failure
               BEFORE INSERT ON bulletins
               BEGIN SELECT RAISE(ABORT, 'forced failure'); END"""
        )
    with pytest.raises(sqlite3.IntegrityError, match="forced failure"):
        store.store_bulletin(**bulletin())
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM bulletins").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT last_value FROM bulletin_sequence WHERE singleton=1"
            ).fetchone()[0]
            == 0
        )
        connection.execute("DROP TRIGGER force_bulletin_failure")
    assert store.store_bulletin(**bulletin()) == 1


def test_failed_later_insert_does_not_create_sequence_gap(tmp_path):
    database, store = create_store(tmp_path / "node.db")
    assert store.store_bulletin(**bulletin()) == 1
    with database.connect() as connection:
        connection.execute(
            """CREATE TRIGGER force_bulletin_failure
               BEFORE INSERT ON bulletins
               BEGIN SELECT RAISE(ABORT, 'forced failure'); END"""
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.store_bulletin(**bulletin(title="rejected"))
    with database.connect() as connection:
        assert (
            connection.execute("SELECT last_value FROM bulletin_sequence").fetchone()[0]
            == 1
        )
        connection.execute("DROP TRIGGER force_bulletin_failure")
    assert store.store_bulletin(**bulletin(title="accepted")) == 2


def test_bulletin_sequence_exhaustion(tmp_path):
    database, store = create_store(tmp_path / "node.db")
    with database.connect() as connection:
        connection.execute("UPDATE bulletin_sequence SET last_value=4294967295")
    with pytest.raises(SequenceExhaustedError):
        store.store_bulletin(**bulletin())


@pytest.mark.parametrize("field", ["author", "title"])
@pytest.mark.parametrize("value", [None, b"bytes", 4, True])
def test_text_fields_require_strings(tmp_path, field, value):
    _, store = create_store(tmp_path / f"{field}-{value!r}.db")
    with pytest.raises(TypeError):
        store.store_bulletin(**bulletin(**{field: value}))


@pytest.mark.parametrize("value", [None, b"bytes", 4, True])
def test_body_requires_string(tmp_path, value):
    _, store = create_store(tmp_path / f"body-{value!r}.db")
    with pytest.raises(TypeError):
        store.store_bulletin(**bulletin(body=value))


@pytest.mark.parametrize("value", [-1, 0x1_0000_0000, True, 1.5, "1", None])
def test_created_at_requires_u32(tmp_path, value):
    _, store = create_store(tmp_path / f"created-{value!r}.db")
    with pytest.raises(ValueError):
        store.store_bulletin(**bulletin(created_at=value))


@pytest.mark.parametrize("value", [-1, True, 1.5, "1", None, 2**63])
def test_clock_validation_rolls_back(tmp_path, value):
    database, store = create_store(
        tmp_path / f"clock-{value!r}.db", clock=lambda: value
    )
    with pytest.raises(ValueError):
        store.store_bulletin(**bulletin())
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM bulletins").fetchone()[0] == 0
        assert (
            connection.execute("SELECT last_value FROM bulletin_sequence").fetchone()[0]
            == 0
        )
