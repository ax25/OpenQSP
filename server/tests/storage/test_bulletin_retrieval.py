import pytest
from openqsp.storage import *


def seed(s, count):
    for i in range(count):
        s.store_bulletin(
            created_at=i + 1, author="EA1AAA", title=f"t{i+1}", body=f"b{i+1}"
        )


def test_empty_and_invalid_cursor(database):
    s = BulletinStore(database)
    assert s.get_new_bulletins(since=0, limit=20).headers == ()
    with pytest.raises(InvalidCursorError):
        s.get_new_bulletins(since=1, limit=20)


def test_headers_and_complete_unicode(database):
    s = BulletinStore(database)
    s.store_bulletin(created_at=1, author="EA1AAA", title="sol ☀", body="radio 📡")
    assert s.get_new_bulletins(since=0, limit=20).headers == (
        StoredBulletinHeader(1, 1, "EA1AAA", "sol ☀"),
    )
    assert s.get_bulletin(sequence=1) == StoredBulletin(
        1, 1, "EA1AAA", "sol ☀", "radio 📡"
    )


def test_pagination(database):
    s = BulletinStore(database)
    seed(s, 5)
    a = s.get_new_bulletins(since=0, limit=2)
    b = s.get_new_bulletins(since=2, limit=2)
    c = s.get_new_bulletins(since=4, limit=2)
    assert (
        [x.sequence for x in a.headers],
        [x.sequence for x in b.headers],
        [x.sequence for x in c.headers],
    ) == ([1, 2], [3, 4], [5])
    assert a.has_more and b.has_more and not c.has_more


@pytest.mark.parametrize("limit", [1, 20])
def test_limit_boundaries(database, limit):
    assert BulletinStore(database).get_new_bulletins(since=0, limit=limit).headers == ()


@pytest.mark.parametrize("limit", [0, 21, True, 1.5])
def test_invalid_limits(database, limit):
    with pytest.raises(ValueError):
        BulletinStore(database).get_new_bulletins(since=0, limit=limit)


@pytest.mark.parametrize("since", [-1, 2**32, True, 1.5])
def test_since_u32(database, since):
    with pytest.raises(ValueError):
        BulletinStore(database).get_new_bulletins(since=since, limit=1)


def test_missing(database):
    assert BulletinStore(database).get_bulletin(sequence=1) is None


def test_restart(database):
    s = BulletinStore(database)
    seed(s, 2)
    assert BulletinStore(database).get_bulletin(sequence=2).title == "t2"


def test_corrupt_body(database):
    s = BulletinStore(database)
    seed(s, 1)
    with database.connect() as c:
        c.execute("UPDATE bulletins SET body=X'FF'")
    with pytest.raises(StorageIntegrityError, match="UTF-8"):
        s.get_bulletin(sequence=1)
