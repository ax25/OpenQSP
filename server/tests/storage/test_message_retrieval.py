"""Tests for mailbox-local private-message retrieval."""

import pytest
from openqsp.storage import (
    Database,
    InvalidCursorError,
    MessageStore,
    StorageIntegrityError,
)


def create_store(path):
    database = Database(path)
    database.initialize()
    return database, MessageStore(database, clock=lambda: 900)


def add(store, recipient="BOX", count=1):
    for number in range(1, count + 1):
        store.store_message(
            created_at=100 + number,
            author="SRC",
            recipient=recipient,
            body=f"body {number}",
        )


def test_retrieval_decodes_every_stored_message_field(tmp_path):
    _, store = create_store(tmp_path / "node.db")
    add(store)
    stored = store.get_new_messages(callsign="BOX", since=0, limit=1).messages[0]
    assert stored.sequence == 1
    assert stored.created_at == 101
    assert stored.accepted_at == 900
    assert stored.author == "SRC"
    assert stored.recipient == "BOX"
    assert stored.body == "body 1"


def test_retrieval_after_restart(tmp_path):
    path = tmp_path / "node.db"
    _, store = create_store(path)
    add(store, count=2)
    reopened = MessageStore(Database(path))
    assert [
        item.sequence
        for item in reopened.get_new_messages(
            callsign="BOX", since=0, limit=20
        ).messages
    ] == [1, 2]


def test_exact_mailbox_local_pagination(tmp_path):
    _, store = create_store(tmp_path / "node.db")
    for number in range(1, 6):
        store.store_message(
            created_at=number, author="SRC", recipient="BOX", body=str(number)
        )
        store.store_message(
            created_at=number, author="SRC", recipient="OTHER", body="other"
        )
    first = store.get_new_messages(callsign="BOX", since=0, limit=2)
    second = store.get_new_messages(callsign="BOX", since=2, limit=2)
    third = store.get_new_messages(callsign="BOX", since=4, limit=2)
    assert ([m.sequence for m in first.messages], first.next_since, first.has_more) == (
        [1, 2],
        2,
        True,
    )
    assert (
        [m.sequence for m in second.messages],
        second.next_since,
        second.has_more,
    ) == ([3, 4], 4, True)
    assert ([m.sequence for m in third.messages], third.next_since, third.has_more) == (
        [5],
        5,
        False,
    )


def test_empty_page_keeps_original_cursor(tmp_path):
    _, store = create_store(tmp_path / "node.db")
    add(store, count=2)
    page = store.get_new_messages(callsign="BOX", since=2, limit=20)
    assert page.messages == ()
    assert page.next_since == 2
    assert page.has_more is False


def test_unknown_empty_mailbox_accepts_zero_and_rejects_positive_cursor(tmp_path):
    _, store = create_store(tmp_path / "node.db")
    assert store.get_new_messages(callsign="UNKNOWN", since=0, limit=1).messages == ()
    with pytest.raises(InvalidCursorError):
        store.get_new_messages(callsign="UNKNOWN", since=1, limit=1)


def test_other_mailbox_activity_does_not_affect_cursor_validity(tmp_path):
    _, store = create_store(tmp_path / "node.db")
    add(store, recipient="OTHER", count=3)
    assert store.get_new_messages(callsign="BOX", since=0, limit=20).messages == ()
    with pytest.raises(InvalidCursorError):
        store.get_new_messages(callsign="BOX", since=1, limit=20)


def test_cursor_ahead_of_local_high_water_is_rejected(tmp_path):
    _, store = create_store(tmp_path / "node.db")
    add(store, count=2)
    with pytest.raises(InvalidCursorError, match="ahead"):
        store.get_new_messages(callsign="BOX", since=3, limit=20)


@pytest.mark.parametrize("limit", [1, 20])
def test_limit_boundaries_are_valid(tmp_path, limit):
    _, store = create_store(tmp_path / f"valid-{limit}.db")
    add(store, count=2)
    page = store.get_new_messages(callsign="BOX", since=0, limit=limit)
    assert len(page.messages) == min(limit, 2)


@pytest.mark.parametrize("limit", [0, 21, True, 1.0, "1", None])
def test_invalid_limits_are_rejected(tmp_path, limit):
    _, store = create_store(tmp_path / f"invalid-{limit!r}.db")
    with pytest.raises(ValueError):
        store.get_new_messages(callsign="BOX", since=0, limit=limit)


@pytest.mark.parametrize("since", [-1, 0x1_0000_0000, True, 1.0, "0", None])
def test_since_must_be_u32(tmp_path, since):
    _, store = create_store(tmp_path / f"since-{since!r}.db")
    with pytest.raises(ValueError):
        store.get_new_messages(callsign="BOX", since=since, limit=1)


@pytest.mark.parametrize("callsign", [None, b"BOX", 1, True])
def test_callsign_must_be_text(tmp_path, callsign):
    _, store = create_store(tmp_path / f"callsign-{callsign!r}.db")
    with pytest.raises(TypeError):
        store.get_new_messages(callsign=callsign, since=0, limit=1)


def test_invalid_utf8_persisted_body_is_reported(tmp_path):
    database, store = create_store(tmp_path / "node.db")
    add(store)
    with database.connect() as connection:
        connection.execute("UPDATE messages SET body=X'FF'")
    with pytest.raises(StorageIntegrityError, match="UTF-8"):
        store.get_new_messages(callsign="BOX", since=0, limit=1)


def test_messages_without_mailbox_state_are_detected(tmp_path):
    database, store = create_store(tmp_path / "node.db")
    add(store)
    with database.connect() as connection:
        connection.execute("DELETE FROM mailbox_sequences WHERE recipient='BOX'")
    with pytest.raises(StorageIntegrityError, match="no sequence state"):
        store.get_new_messages(callsign="BOX", since=0, limit=1)


def test_high_water_behind_persisted_message_is_detected(tmp_path):
    database, store = create_store(tmp_path / "node.db")
    add(store, count=2)
    with database.connect() as connection:
        connection.execute(
            "UPDATE mailbox_sequences SET last_value=1 WHERE recipient='BOX'"
        )
    with pytest.raises(StorageIntegrityError, match="behind"):
        store.get_new_messages(callsign="BOX", since=0, limit=20)


@pytest.mark.parametrize("corrupt", [-1, 0x1_0000_0000, "bad", b"bad"])
def test_corrupt_mailbox_high_water_is_reported(tmp_path, corrupt):
    database, store = create_store(tmp_path / f"corrupt-{corrupt!r}.db")
    with database.connect() as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(
            "INSERT INTO mailbox_sequences VALUES ('BOX', ?)", (corrupt,)
        )
    with pytest.raises(StorageIntegrityError):
        store.get_new_messages(callsign="BOX", since=0, limit=1)
