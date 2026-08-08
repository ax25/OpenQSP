"""Tests for incremental private-message retrieval."""

from __future__ import annotations

import pytest

from openqsp.storage import (
    Database,
    InvalidCursorError,
    MessageStore,
    StorageIntegrityError,
)
from openqsp.storage.migrations import encode_u64


@pytest.fixture
def database(tmp_path) -> Database:
    database = Database(tmp_path / "node.db")
    database.initialize()
    return database


def _store(database: Database, recipients: list[str]) -> MessageStore:
    store = MessageStore(database, clock=lambda: 1_000)
    for message_id, recipient in enumerate(recipients, start=1):
        store.store_message(
            message_id=message_id,
            created_at=500 + message_id,
            author="EA9SRC",
            recipient=recipient,
            body=f"message {message_id}",
        )
    return store


def _sequences(page) -> list[int]:
    return [message.sequence for message in page.messages]


def test_empty_store_and_invalid_cursor(database) -> None:
    store = MessageStore(database)

    page = store.get_new_messages(callsign="EA1ABC", since=0, limit=20)

    assert page.messages == ()
    assert (page.next_since, page.has_more) == (0, False)
    with pytest.raises(InvalidCursorError, match="ahead"):
        store.get_new_messages(callsign="EA1ABC", since=1, limit=20)


def test_returns_complete_visible_message(database) -> None:
    store = _store(database, ["EA1ABC"])

    page = store.get_new_messages(callsign="EA1ABC", since=0, limit=20)

    assert len(page.messages) == 1
    message = page.messages[0]
    assert (
        message.sequence,
        message.message_id,
        message.created_at,
        message.author,
        message.recipient,
        message.body,
    ) == (1, 1, 501, "EA9SRC", "EA1ABC", "message 1")
    assert (page.next_since, page.has_more) == (1, False)


def test_filters_by_recipient_and_accepts_invisible_cursor(database) -> None:
    store = _store(database, ["EA1ABC", "EA2XYZ", "EA1ABC"])

    first = store.get_new_messages(callsign="EA1ABC", since=0, limit=20)
    after_invisible = store.get_new_messages(callsign="EA1ABC", since=2, limit=20)

    assert _sequences(first) == [1, 3]
    assert _sequences(after_invisible) == [3]


def test_paginates_visible_messages(database) -> None:
    store = _store(database, ["EA1ABC"] * 3)

    first = store.get_new_messages(callsign="EA1ABC", since=0, limit=2)
    second = store.get_new_messages(callsign="EA1ABC", since=2, limit=2)

    assert (_sequences(first), first.next_since, first.has_more) == ([1, 2], 2, True)
    assert (_sequences(second), second.next_since, second.has_more) == ([3], 3, False)


def test_pagination_limit_applies_after_interleaved_recipient_filter(database) -> None:
    store = _store(
        database, ["EA1ABC", "EA2XYZ", "EA1ABC", "EA2XYZ", "EA1ABC"]
    )

    first = store.get_new_messages(callsign="EA1ABC", since=0, limit=2)
    second = store.get_new_messages(callsign="EA1ABC", since=3, limit=2)

    assert (_sequences(first), first.next_since, first.has_more) == ([1, 3], 3, True)
    assert (_sequences(second), second.next_since, second.has_more) == ([5], 5, False)


def test_empty_page_preserves_valid_requested_cursor(database) -> None:
    store = _store(database, ["EA2XYZ"] * 10)

    page = store.get_new_messages(callsign="EA1ABC", since=8, limit=20)
    at_highest = store.get_new_messages(callsign="EA1ABC", since=10, limit=20)

    assert (page.messages, page.next_since, page.has_more) == ((), 8, False)
    assert (at_highest.messages, at_highest.next_since, at_highest.has_more) == (
        (),
        10,
        False,
    )
    with pytest.raises(InvalidCursorError):
        store.get_new_messages(callsign="EA1ABC", since=11, limit=20)


@pytest.mark.parametrize("limit", [1, 20])
def test_limit_boundaries_are_valid(database, limit) -> None:
    page = MessageStore(database).get_new_messages(
        callsign="EA1ABC", since=0, limit=limit
    )
    assert page.messages == ()


@pytest.mark.parametrize("limit", [0, 21, True, 1.5])
def test_invalid_limits_are_rejected(database, limit) -> None:
    with pytest.raises(ValueError, match="limit"):
        MessageStore(database).get_new_messages(
            callsign="EA1ABC", since=0, limit=limit
        )


@pytest.mark.parametrize("since", [-1, 2**64, True, 1.5])
def test_since_must_be_u64(database, since) -> None:
    with pytest.raises(ValueError, match="since"):
        MessageStore(database).get_new_messages(
            callsign="EA1ABC", since=since, limit=1
        )


def test_unsigned_blob_order_crosses_signed_integer_boundary(database) -> None:
    low = 0x7FFF_FFFF_FFFF_FFFF
    high = 0x8000_0000_0000_0000
    with database.connect() as connection:
        connection.execute("BEGIN")
        for sequence, message_id in [(low, 1), (high, 2)]:
            encoded_id = encode_u64(message_id)
            connection.execute(
                "INSERT INTO objects VALUES (?, 'message')", (encoded_id,)
            )
            connection.execute(
                """INSERT INTO messages VALUES (?, ?, 1, 1, 'EA9SRC',
                                                  'EA1ABC', ?, X'00')""",
                (encode_u64(sequence), encoded_id, f"body {message_id}".encode()),
            )
        connection.execute(
            "UPDATE sequences SET last_value = ? WHERE stream = 'messages'",
            (encode_u64(high),),
        )
        connection.commit()

    page = MessageStore(database).get_new_messages(
        callsign="EA1ABC", since=low - 1, limit=20
    )

    assert _sequences(page) == [low, high]
    assert page.next_since == high


def test_retrieval_survives_database_restart(tmp_path) -> None:
    path = tmp_path / "restart.db"
    database = Database(path)
    database.initialize()
    expected = _store(database, ["EA1ABC", "EA1ABC"]).get_new_messages(
        callsign="EA1ABC", since=0, limit=20
    )

    reopened = Database(path)
    reopened.initialize()
    actual = MessageStore(reopened).get_new_messages(
        callsign="EA1ABC", since=0, limit=20
    )

    assert actual == expected


def test_corrupt_utf8_body_raises_integrity_error(database) -> None:
    _store(database, ["EA1ABC"])
    with database.connect() as connection:
        connection.execute("UPDATE messages SET body = X'FF'")

    with pytest.raises(StorageIntegrityError, match="UTF-8"):
        MessageStore(database).get_new_messages(
            callsign="EA1ABC", since=0, limit=20
        )
