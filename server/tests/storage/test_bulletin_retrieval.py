"""Tests for incremental headers and complete public-bulletin retrieval."""

from __future__ import annotations

import pytest

from openqsp.storage import (
    BulletinStore,
    Database,
    InvalidCursorError,
    MessageStore,
    StorageIntegrityError,
    StoredBulletin,
    StoredBulletinHeader,
)
from openqsp.storage.migrations import encode_u64


@pytest.fixture
def database(tmp_path) -> Database:
    database = Database(tmp_path / "node.db")
    database.initialize()
    return database


def _store(database: Database, count: int = 3) -> BulletinStore:
    store = BulletinStore(database, clock=lambda: 1_000)
    for bulletin_id in range(1, count + 1):
        store.store_bulletin(
            bulletin_id=bulletin_id,
            created_at=500 + bulletin_id,
            author="EA9SRC",
            title=f"Bulletin {bulletin_id}",
            body=f"Full body {bulletin_id}",
        )
    return store


def _sequences(page) -> list[int]:
    return [header.sequence for header in page.headers]


def test_empty_store_and_invalid_cursor(database) -> None:
    store = BulletinStore(database)

    page = store.get_new_bulletins(since=0, limit=20)

    assert (page.headers, page.next_since, page.has_more) == ((), 0, False)
    with pytest.raises(InvalidCursorError, match="ahead"):
        store.get_new_bulletins(since=1, limit=20)


def test_returns_header_without_requiring_body(database) -> None:
    store = BulletinStore(database, clock=lambda: 1_000)
    store.store_bulletin(
        bulletin_id=42,
        created_at=500,
        author="EA1ABC",
        title="Solar activity",
        body="Full body",
    )
    # A corrupt body cannot affect a header-only SELECT or header decoding.
    with database.connect() as connection:
        connection.execute("UPDATE bulletins SET body = X'FF'")

    page = store.get_new_bulletins(since=0, limit=20)

    assert page.headers == (
        StoredBulletinHeader(1, 42, 500, "EA1ABC", "Solar activity"),
    )


def test_orders_multiple_headers_and_applies_cursor(database) -> None:
    store = _store(database)

    assert _sequences(store.get_new_bulletins(since=0, limit=20)) == [1, 2, 3]
    assert _sequences(store.get_new_bulletins(since=1, limit=20)) == [2, 3]


def test_paginates_with_limit_plus_one(database) -> None:
    store = _store(database)

    first = store.get_new_bulletins(since=0, limit=2)
    second = store.get_new_bulletins(since=2, limit=2)

    assert (_sequences(first), first.next_since, first.has_more) == ([1, 2], 2, True)
    assert (_sequences(second), second.next_since, second.has_more) == ([3], 3, False)


def test_exactly_limit_items_does_not_report_more(database) -> None:
    page = _store(database, 2).get_new_bulletins(since=0, limit=2)

    assert (_sequences(page), page.next_since, page.has_more) == ([1, 2], 2, False)


def test_empty_page_at_highest_and_cursor_beyond_highest(database) -> None:
    store = _store(database)

    page = store.get_new_bulletins(since=3, limit=20)

    assert (page.headers, page.next_since, page.has_more) == ((), 3, False)
    with pytest.raises(InvalidCursorError):
        store.get_new_bulletins(since=4, limit=20)


@pytest.mark.parametrize("limit", [1, 20])
def test_limit_boundaries_are_valid(database, limit) -> None:
    assert BulletinStore(database).get_new_bulletins(
        since=0, limit=limit
    ).headers == ()


@pytest.mark.parametrize("limit", [0, 21, True, 1.5])
def test_invalid_limits_are_rejected(database, limit) -> None:
    with pytest.raises(ValueError, match="limit"):
        BulletinStore(database).get_new_bulletins(since=0, limit=limit)


@pytest.mark.parametrize("since", [-1, 2**64, True, 1.5])
def test_since_must_be_u64(database, since) -> None:
    with pytest.raises(ValueError, match="since"):
        BulletinStore(database).get_new_bulletins(since=since, limit=1)


def test_get_bulletin_returns_complete_unicode_object(database) -> None:
    store = BulletinStore(database, clock=lambda: 1_000)
    store.store_bulletin(
        bulletin_id=42,
        created_at=500,
        author="EA1ABC",
        title="Actividad solar ☀",
        body="Próxima apertura 📡",
    )

    assert store.get_bulletin(bulletin_id=42) == StoredBulletin(
        42, 500, "EA1ABC", "Actividad solar ☀", "Próxima apertura 📡"
    )


def test_get_bulletin_returns_none_for_missing_and_message_ids(database) -> None:
    MessageStore(database).store_message(
        message_id=42,
        created_at=500,
        author="EA1ABC",
        recipient="EA2XYZ",
        body="Private",
    )
    store = BulletinStore(database)

    assert store.get_bulletin(bulletin_id=41) is None
    assert store.get_bulletin(bulletin_id=42) is None


def test_get_bulletin_accepts_full_u64_id(database) -> None:
    maximum = 0xFFFF_FFFF_FFFF_FFFF
    store = BulletinStore(database)
    store.store_bulletin(
        bulletin_id=maximum,
        created_at=1,
        author="EA1ABC",
        title="Maximum",
        body="Unsigned identifier",
    )

    assert store.get_bulletin(bulletin_id=maximum).bulletin_id == maximum


def test_unsigned_sequence_order_crosses_signed_boundary(database) -> None:
    low = 0x7FFF_FFFF_FFFF_FFFF
    high = 0x8000_0000_0000_0000
    with database.connect() as connection:
        connection.execute("BEGIN")
        for sequence, bulletin_id in ((low, 1), (high, 2)):
            encoded_id = encode_u64(bulletin_id)
            connection.execute(
                "INSERT INTO objects VALUES (?, 'bulletin')", (encoded_id,)
            )
            connection.execute(
                """INSERT INTO bulletins VALUES (
                       ?, ?, 1, 1, 'EA9SRC', ?, ?, X'00')""",
                (
                    encode_u64(sequence),
                    encoded_id,
                    f"Title {bulletin_id}",
                    f"Body {bulletin_id}".encode(),
                ),
            )
        connection.execute(
            "UPDATE sequences SET last_value = ? WHERE stream = 'bulletins'",
            (encode_u64(high),),
        )
        connection.commit()

    page = BulletinStore(database).get_new_bulletins(since=low - 1, limit=20)

    assert _sequences(page) == [low, high]
    assert page.next_since == high


def test_retrieval_survives_database_restart(tmp_path) -> None:
    path = tmp_path / "restart.db"
    database = Database(path)
    database.initialize()
    store = _store(database, 2)
    expected_page = store.get_new_bulletins(since=0, limit=20)
    expected_bulletin = store.get_bulletin(bulletin_id=2)

    reopened = Database(path)
    reopened.initialize()
    reopened_store = BulletinStore(reopened)

    assert reopened_store.get_new_bulletins(since=0, limit=20) == expected_page
    assert reopened_store.get_bulletin(bulletin_id=2) == expected_bulletin


def test_corrupt_utf8_body_raises_integrity_error(database) -> None:
    store = _store(database, 1)
    with database.connect() as connection:
        connection.execute("UPDATE bulletins SET body = X'FF'")

    with pytest.raises(StorageIntegrityError, match="UTF-8"):
        store.get_bulletin(bulletin_id=1)
