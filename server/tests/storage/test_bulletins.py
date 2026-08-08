import pytest
from openqsp.storage import *
from openqsp.storage._common import MAX_U32


def test_sequence_is_identity(database):
    s = BulletinStore(database, clock=lambda: 9)
    a = s.store_bulletin(created_at=1, author="EA1AAA", title="a", body="b")
    assert a.sequence == 1
    assert s.get_bulletin(sequence=1).title == "a"


@pytest.mark.parametrize("value", [-1, 2**32, True, 1.5])
def test_created_at_u32(database, value):
    with pytest.raises(ValueError):
        BulletinStore(database).store_bulletin(
            created_at=value, author="EA1AAA", title="a", body="b"
        )


@pytest.mark.parametrize("key,value", [("author", 1), ("title", 1), ("body", 1)])
def test_text_types(database, key, value):
    args = dict(created_at=1, author="EA1AAA", title="a", body="b")
    args[key] = value
    with pytest.raises(TypeError):
        BulletinStore(database).store_bulletin(**args)


def test_clock_rollback(database):
    with pytest.raises(ValueError):
        BulletinStore(database, clock=lambda: -1).store_bulletin(
            created_at=1, author="EA1AAA", title="a", body="b"
        )
    assert (
        BulletinStore(database)
        .store_bulletin(created_at=1, author="EA1AAA", title="a", body="b")
        .sequence
        == 1
    )


def test_exhaustion(database):
    with database.connect() as c:
        c.execute("UPDATE bulletin_sequence SET last_value=?", (MAX_U32,))
    with pytest.raises(SequenceExhaustedError):
        BulletinStore(database).store_bulletin(
            created_at=1, author="EA1AAA", title="a", body="b"
        )
