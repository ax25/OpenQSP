"""Tests for atomic private-message persistence and allocation."""

from __future__ import annotations

import concurrent.futures
import sqlite3

import pytest
from openqsp.storage import Database, MessageStore, SequenceExhaustedError


def create_store(path, *, clock=lambda: 1_700_000_000):
    database = Database(path)
    database.initialize()
    return database, MessageStore(database, clock=clock)


def message(**changes):
    values = {
        "created_at": 123,
        "author": "EA1ABC",
        "recipient": "EA3GNU",
        "body": "hello \N{EARTH GLOBE EUROPE-AFRICA}",
    }
    values.update(changes)
    return values


def test_store_message_persists_complete_row_and_returns_sequence(tmp_path):
    database, store = create_store(tmp_path / "node.db", clock=lambda: 456)
    assert store.store_message(**message()) == 1

    with database.connect() as connection:
        row = connection.execute(
            """SELECT recipient, mailbox_sequence, author, created_at,
                      accepted_at, body FROM messages"""
        ).fetchone()
    assert tuple(row) == ("EA3GNU", 1, "EA1ABC", 123, 456, "hello 🌍".encode())


def test_api_list_preserves_persisted_api_sequence(tmp_path):
    _, store = create_store(tmp_path / "node.db")
    store.store_message(**message(body="first"))
    store.store_message(**message(body="second"))

    stored, has_more = store.api_list(callsign="EA3GNU", limit=1)

    assert has_more is True
    assert stored[0].api_sequence == 1
    next_page, has_more = store.api_list(
        callsign="EA3GNU", after=stored[0].api_sequence, limit=1
    )
    assert has_more is False
    assert next_page[0].api_sequence == 2
    assert next_page[0].body == "second"


def test_first_and_second_message_receive_one_and_two(tmp_path):
    _, store = create_store(tmp_path / "node.db")
    assert store.store_message(**message(body="first")) == 1
    assert store.store_message(**message(body="second")) == 2


def test_interleaved_mailboxes_allocate_independently(tmp_path):
    _, store = create_store(tmp_path / "node.db")
    recipients = ["EA3GNU", "EA3ABC", "EA3GNU", "EA3ABC"]
    sequences = [
        store.store_message(**message(recipient=value)) for value in recipients
    ]
    assert sequences == [1, 1, 2, 2]


def test_concurrent_same_mailbox_allocations_are_unique(tmp_path):
    database, _ = create_store(tmp_path / "node.db")

    def write(index):
        return MessageStore(database).store_message(
            **message(created_at=index, body=str(index))
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        sequences = list(pool.map(write, range(40)))
    assert sorted(sequences) == list(range(1, 41))


def test_high_water_survives_restart(tmp_path):
    path = tmp_path / "node.db"
    _, store = create_store(path)
    assert store.store_message(**message()) == 1
    reopened = MessageStore(Database(path))
    assert reopened.store_message(**message(body="after restart")) == 2


def test_failed_first_insert_rolls_back_new_high_water_row(tmp_path):
    database, store = create_store(tmp_path / "node.db")
    with database.connect() as connection:
        connection.execute(
            """CREATE TRIGGER force_message_failure
               BEFORE INSERT ON messages
               BEGIN SELECT RAISE(ABORT, 'forced failure'); END"""
        )
    with pytest.raises(sqlite3.IntegrityError, match="forced failure"):
        store.store_message(**message())
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        assert (
            connection.execute("SELECT count(*) FROM mailbox_sequences").fetchone()[0]
            == 0
        )
        connection.execute("DROP TRIGGER force_message_failure")
    assert store.store_message(**message()) == 1


def test_failed_later_insert_restores_existing_high_water(tmp_path):
    database, store = create_store(tmp_path / "node.db")
    assert store.store_message(**message(body="kept")) == 1
    with database.connect() as connection:
        connection.execute(
            """CREATE TRIGGER force_message_failure
               BEFORE INSERT ON messages
               BEGIN SELECT RAISE(ABORT, 'forced failure'); END"""
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.store_message(**message(body="rejected"))
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT last_value FROM mailbox_sequences WHERE recipient='EA3GNU'"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 1
        connection.execute("DROP TRIGGER force_message_failure")
    assert store.store_message(**message(body="accepted")) == 2


def test_last_u32_sequence_can_be_allocated_then_space_is_exhausted(tmp_path):
    database, store = create_store(tmp_path / "node.db")
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO mailbox_sequences VALUES ('EA3GNU', 4294967294)"
        )
    assert store.store_message(**message()) == 0xFFFF_FFFF
    with pytest.raises(SequenceExhaustedError):
        store.store_message(**message(body="too late"))


@pytest.mark.parametrize("field", ["author", "recipient"])
@pytest.mark.parametrize("value", [None, b"bytes", 3, True])
def test_callsign_fields_must_be_strings(tmp_path, field, value):
    _, store = create_store(tmp_path / f"{field}-{value!r}.db")
    with pytest.raises(TypeError):
        store.store_message(**message(**{field: value}))


@pytest.mark.parametrize("value", [None, b"bytes", 3, True])
def test_body_must_be_a_string(tmp_path, value):
    _, store = create_store(tmp_path / f"body-{value!r}.db")
    with pytest.raises(TypeError):
        store.store_message(**message(body=value))


@pytest.mark.parametrize("value", [-1, 0x1_0000_0000, True, 1.5, "1", None])
def test_created_at_must_be_u32(tmp_path, value):
    _, store = create_store(tmp_path / f"created-{value!r}.db")
    with pytest.raises(ValueError):
        store.store_message(**message(created_at=value))


@pytest.mark.parametrize("value", [-1, True, 1.5, "1", None, 2**63])
def test_clock_value_is_validated_and_failure_rolls_back(tmp_path, value):
    database, store = create_store(
        tmp_path / f"clock-{value!r}.db", clock=lambda: value
    )
    with pytest.raises(ValueError):
        store.store_message(**message())
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        assert (
            connection.execute("SELECT count(*) FROM mailbox_sequences").fetchone()[0]
            == 0
        )


def test_conversation_read_state_survives_store_reopen(tmp_path):
    path = tmp_path / "reads.db"
    database, store = create_store(path)
    store.store_message(**message(author="EA1ABC", recipient="EA3GNU", body="old"))
    assert store.conversations(callsign="EA3GNU")[0].unread_count == 1
    assert store.mark_conversation_read(owner="EA3GNU", peer="EA1ABC") == 1

    reopened = MessageStore(Database(path))
    conversation = reopened.conversations(callsign="EA3GNU")[0]
    assert conversation.unread_count == 0
    assert conversation.last_read_sequence == 1
    assert reopened.mark_conversation_read(owner="EA3GNU", peer="EA9NONE") == 0
