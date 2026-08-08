import pytest
from openqsp.storage import (
    BulletinStore,
    Database,
    InvalidCursorError,
    StorageIntegrityError,
)


def setup(tmp_path):
    db = Database(tmp_path / "db")
    db.initialize()
    return db, BulletinStore(db, clock=lambda: 9)


def test_pagination_and_sequence_lookup(tmp_path):
    _, s = setup(tmp_path)
    for i in range(3):
        s.store_bulletin(created_at=i, author="A", title=str(i), body="b")
    p = s.get_new_bulletins(since=0, limit=2)
    assert (
        [h.sequence for h in p.headers] == [1, 2] and p.has_more and p.next_since == 2
    )
    assert s.get_bulletin(sequence=3).title == "2"
    assert s.get_bulletin(sequence=0) is None


def test_cursor_boundaries(tmp_path):
    _, s = setup(tmp_path)
    assert s.get_new_bulletins(since=0, limit=1).headers == ()
    with pytest.raises(InvalidCursorError):
        s.get_new_bulletins(since=1, limit=1)
    for bad in (-1, 0x100000000, True, "0"):
        with pytest.raises(ValueError):
            s.get_new_bulletins(since=bad, limit=1)


def test_invalid_utf8_is_reported(tmp_path):
    db, s = setup(tmp_path)
    s.store_bulletin(created_at=1, author="A", title="T", body="b")
    with db.connect() as c:
        c.execute("UPDATE bulletins SET body=X'FF'")
    with pytest.raises(StorageIntegrityError):
        s.get_bulletin(sequence=1)
