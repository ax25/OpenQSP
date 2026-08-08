"""Tests for bulletin synchronization and sequence lookup."""

import pytest

from openqsp.storage import (
    BulletinStore,
    Database,
    InvalidCursorError,
    StorageIntegrityError,
)


def create_store(path):
    database = Database(path)
    database.initialize()
    return database, BulletinStore(database, clock=lambda: 800)


def add(store, count=1):
    for number in range(1, count + 1):
        store.store_bulletin(
            created_at=100 + number,
            author="SRC",
            title=f"Title {number} ☕",
            body=f"Body {number} 🌍",
        )


def test_complete_header_and_bulletin_values(tmp_path):
    _, store = create_store(tmp_path / "node.db")
    add(store)
    header = store.get_new_bulletins(since=0, limit=1).headers[0]
    assert (header.sequence, header.created_at, header.author, header.title) == (
        1,
        101,
        "SRC",
        "Title 1 ☕",
    )
    item = store.get_bulletin(sequence=1)
    assert (item.sequence, item.created_at, item.accepted_at) == (1, 101, 800)
    assert (item.author, item.title, item.body) == ("SRC", "Title 1 ☕", "Body 1 🌍")


def test_retrieval_after_restart_and_missing_lookup(tmp_path):
    path = tmp_path / "node.db"
    _, store = create_store(path)
    add(store)
    reopened = BulletinStore(Database(path))
    assert reopened.get_bulletin(sequence=1).body == "Body 1 🌍"
    assert reopened.get_bulletin(sequence=2) is None


def test_sequence_lookup_validation_boundaries(tmp_path):
    database, store = create_store(tmp_path / "node.db")
    add(store)
    assert store.get_bulletin(sequence=1).sequence == 1
    assert store.get_bulletin(sequence=0xFFFF_FFFF) is None
    for invalid in (0, -1, 0x1_0000_0000, True):
        with pytest.raises(ValueError):
            store.get_bulletin(sequence=invalid)


def test_exact_pagination_and_empty_page_at_high_water(tmp_path):
    _, store = create_store(tmp_path / "node.db")
    add(store, count=5)
    first = store.get_new_bulletins(since=0, limit=2)
    second = store.get_new_bulletins(since=2, limit=2)
    third = store.get_new_bulletins(since=4, limit=2)
    empty = store.get_new_bulletins(since=5, limit=20)
    assert ([h.sequence for h in first.headers], first.next_since, first.has_more) == (
        [1, 2],
        2,
        True,
    )
    assert (
        [h.sequence for h in second.headers],
        second.next_since,
        second.has_more,
    ) == ([3, 4], 4, True)
    assert ([h.sequence for h in third.headers], third.next_since, third.has_more) == (
        [5],
        5,
        False,
    )
    assert (empty.headers, empty.next_since, empty.has_more) == ((), 5, False)


def test_empty_stream_and_cursor_ahead_rules(tmp_path):
    _, store = create_store(tmp_path / "node.db")
    assert store.get_new_bulletins(since=0, limit=1).headers == ()
    with pytest.raises(InvalidCursorError):
        store.get_new_bulletins(since=1, limit=1)
    add(store)
    with pytest.raises(InvalidCursorError):
        store.get_new_bulletins(since=2, limit=1)


@pytest.mark.parametrize("limit", [1, 20])
def test_limit_boundaries_are_valid(tmp_path, limit):
    _, store = create_store(tmp_path / f"valid-{limit}.db")
    add(store, count=2)
    assert len(store.get_new_bulletins(since=0, limit=limit).headers) == min(limit, 2)


@pytest.mark.parametrize("limit", [0, 21, True, 1.0, "1", None])
def test_invalid_limits_are_rejected(tmp_path, limit):
    _, store = create_store(tmp_path / f"invalid-{limit!r}.db")
    with pytest.raises(ValueError):
        store.get_new_bulletins(since=0, limit=limit)


@pytest.mark.parametrize("since", [-1, 0x1_0000_0000, True, 1.0, "0", None])
def test_since_requires_u32(tmp_path, since):
    _, store = create_store(tmp_path / f"since-{since!r}.db")
    with pytest.raises(ValueError):
        store.get_new_bulletins(since=since, limit=1)


def test_invalid_body_does_not_break_header_retrieval(tmp_path):
    database, store = create_store(tmp_path / "node.db")
    add(store)
    with database.connect() as connection:
        connection.execute("UPDATE bulletins SET body=X'FF'")
    assert store.get_new_bulletins(since=0, limit=1).headers[0].sequence == 1
    with pytest.raises(StorageIntegrityError, match="UTF-8"):
        store.get_bulletin(sequence=1)
