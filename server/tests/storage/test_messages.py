import concurrent.futures

import pytest

from openqsp.storage import Database, MessageStore, SequenceExhaustedError


def store(path, clock=lambda: 100):
    db = Database(path)
    db.initialize()
    return db, MessageStore(db, clock=clock)


def test_mailboxes_allocate_independent_sequences(tmp_path):
    _, messages = store(tmp_path / "db")
    assert (
        messages.store_message(created_at=1, author="A", recipient="EA3GNU", body="one")
        == 1
    )
    assert (
        messages.store_message(
            created_at=2, author="A", recipient="EA3ABC", body="other"
        )
        == 1
    )
    assert (
        messages.store_message(created_at=3, author="A", recipient="EA3GNU", body="two")
        == 2
    )
    assert (
        messages.store_message(
            created_at=4, author="A", recipient="EA3ABC", body="again"
        )
        == 2
    )


def test_concurrent_writes_are_unique(tmp_path):
    path = tmp_path / "db"
    db, _ = store(path)

    def write(i):
        return MessageStore(db).store_message(
            created_at=i, author="A", recipient="BOX", body=str(i)
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(write, range(30)))
    assert sorted(values) == list(range(1, 31))


def test_high_water_survives_restart(tmp_path):
    path = tmp_path / "db"
    _, messages = store(path)
    messages.store_message(created_at=1, author="A", recipient="BOX", body="x")
    assert (
        MessageStore(Database(path)).store_message(
            created_at=2, author="A", recipient="BOX", body="y"
        )
        == 2
    )


def test_maximum_and_exhaustion(tmp_path):
    db, messages = store(tmp_path / "db")
    with db.connect() as connection:
        connection.execute("INSERT INTO mailbox_sequences VALUES ('BOX', 4294967294)")
    assert (
        messages.store_message(created_at=1, author="A", recipient="BOX", body="last")
        == 0xFFFFFFFF
    )
    with pytest.raises(SequenceExhaustedError):
        messages.store_message(created_at=1, author="A", recipient="BOX", body="no")


@pytest.mark.parametrize("created_at", [-1, 0x100000000, True, "1"])
def test_created_at_must_be_u32(tmp_path, created_at):
    _, messages = store(tmp_path / "db")
    with pytest.raises(ValueError):
        messages.store_message(
            created_at=created_at, author="A", recipient="B", body="x"
        )


@pytest.mark.parametrize(
    "clock", [lambda: -1, lambda: True, lambda: "1", lambda: 2**63]
)
def test_clock_validation_rolls_back(tmp_path, clock):
    db, messages = store(tmp_path / "db", clock)
    with pytest.raises(ValueError):
        messages.store_message(created_at=1, author="A", recipient="B", body="x")
    assert (
        MessageStore(db).store_message(
            created_at=1, author="A", recipient="B", body="x"
        )
        == 1
    )
