import pytest
from openqsp.storage import (
    Database,
    InvalidCursorError,
    MessageStore,
    StorageIntegrityError,
)


def setup(tmp_path):
    db = Database(tmp_path / "db")
    db.initialize()
    return db, MessageStore(db, clock=lambda: 77)


def test_empty_mailbox_cursor_rules_and_isolation(tmp_path):
    _, store = setup(tmp_path)
    assert store.get_new_messages(callsign="EMPTY", since=0, limit=20).messages == ()
    store.store_message(created_at=1, author="A", recipient="OTHER", body="x")
    assert store.get_new_messages(callsign="EMPTY", since=0, limit=20).messages == ()
    with pytest.raises(InvalidCursorError):
        store.get_new_messages(callsign="EMPTY", since=1, limit=20)


def test_mailbox_local_pagination_and_metadata(tmp_path):
    _, store = setup(tmp_path)
    for i in range(5):
        store.store_message(created_at=i, author="A", recipient="BOX", body=str(i))
        store.store_message(created_at=i, author="A", recipient="OTHER", body="z")
    page = store.get_new_messages(callsign="BOX", since=0, limit=2)
    assert [m.sequence for m in page.messages] == [1, 2]
    assert page.messages[0].accepted_at == 77
    assert (page.next_since, page.has_more) == (2, True)
    last = store.get_new_messages(callsign="BOX", since=4, limit=2)
    assert ([m.sequence for m in last.messages], last.next_since, last.has_more) == (
        [5],
        5,
        False,
    )
    empty = store.get_new_messages(callsign="BOX", since=5, limit=2)
    assert (empty.next_since, empty.has_more) == (5, False)


@pytest.mark.parametrize("since", [-1, 0x100000000, True, "0"])
def test_cursor_must_be_u32(tmp_path, since):
    _, store = setup(tmp_path)
    with pytest.raises(ValueError):
        store.get_new_messages(callsign="B", since=since, limit=1)


def test_invalid_utf8_and_corrupt_row_are_reported(tmp_path):
    db, store = setup(tmp_path)
    store.store_message(created_at=1, author="A", recipient="B", body="x")
    with db.connect() as c:
        c.execute("UPDATE messages SET body=X'FF' WHERE recipient='B'")
    with pytest.raises(StorageIntegrityError):
        store.get_new_messages(callsign="B", since=0, limit=1)
