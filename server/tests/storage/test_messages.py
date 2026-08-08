import concurrent.futures, sqlite3
import pytest
from openqsp.storage import *
from openqsp.storage._common import MAX_U32


def test_sequences_are_per_recipient(database):
    s = MessageStore(database, clock=lambda: 9)
    assert (
        s.store_message(
            created_at=1, author="EA1AAA", recipient="EA2AAA", body="a"
        ).sequence
        == 1
    )
    assert (
        s.store_message(
            created_at=2, author="EA1AAA", recipient="EA2AAA", body="b"
        ).sequence
        == 2
    )
    assert (
        s.store_message(
            created_at=3, author="EA1AAA", recipient="EA3AAA", body="c"
        ).sequence
        == 1
    )


@pytest.mark.parametrize(
    "field,value", [("created_at", -1), ("created_at", 2**32), ("created_at", True)]
)
def test_invalid_integer(database, field, value):
    with pytest.raises(ValueError):
        MessageStore(database).store_message(
            created_at=value, author="EA1AAA", recipient="EA2AAA", body="x"
        )


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"author": 1}, TypeError),
        ({"recipient": 1}, TypeError),
        ({"body": 1}, TypeError),
    ],
)
def test_invalid_text_types(database, changes, error):
    args = dict(created_at=1, author="EA1AAA", recipient="EA2AAA", body="x")
    args.update(changes)
    with pytest.raises(error):
        MessageStore(database).store_message(**args)


def test_bad_clock_rolls_back(database):
    s = MessageStore(database, clock=lambda: -1)
    with pytest.raises(ValueError):
        s.store_message(created_at=1, author="EA1AAA", recipient="EA2AAA", body="x")
    assert (
        MessageStore(database)
        .store_message(created_at=1, author="EA1AAA", recipient="EA2AAA", body="x")
        .sequence
        == 1
    )


def test_exhaustion(database):
    with database.connect() as c:
        c.execute("INSERT INTO mailbox_sequences VALUES('EA2AAA',?)", (MAX_U32,))
    with pytest.raises(SequenceExhaustedError):
        MessageStore(database).store_message(
            created_at=1, author="EA1AAA", recipient="EA2AAA", body="x"
        )


def test_concurrent_unique_monotonic(database):
    s = MessageStore(database)

    def put(i):
        return s.store_message(
            created_at=i + 1, author="EA1AAA", recipient="EA2AAA", body=str(i)
        ).sequence

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as p:
        result = list(p.map(put, range(30)))
    assert sorted(result) == list(range(1, 31))
