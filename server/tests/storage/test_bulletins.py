import pytest
from openqsp.storage import BulletinStore, Database, SequenceExhaustedError


def setup(tmp_path, clock=lambda: 88):
    db = Database(tmp_path / "db")
    db.initialize()
    return db, BulletinStore(db, clock=clock)


def test_sequence_acceptance_and_restart(tmp_path):
    db, store = setup(tmp_path)
    assert store.store_bulletin(created_at=1, author="A", title="T", body="B") == 1
    item = store.get_bulletin(sequence=1)
    assert (item.sequence, item.accepted_at, item.body) == (1, 88, "B")
    assert (
        BulletinStore(db).store_bulletin(created_at=2, author="A", title="U", body="C")
        == 2
    )


def test_exhaustion(tmp_path):
    db, store = setup(tmp_path)
    with db.connect() as c:
        c.execute("UPDATE bulletin_sequence SET last_value=4294967295")
    with pytest.raises(SequenceExhaustedError):
        store.store_bulletin(created_at=1, author="A", title="T", body="B")


@pytest.mark.parametrize("value", [-1, 0x100000000, True, "1"])
def test_created_at_is_u32(tmp_path, value):
    _, store = setup(tmp_path)
    with pytest.raises(ValueError):
        store.store_bulletin(created_at=value, author="A", title="T", body="B")
