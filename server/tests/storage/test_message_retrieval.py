import pytest
from openqsp.storage import *


def seed(s, recipient, count):
    for i in range(count):
        s.store_message(
            created_at=i + 1, author="EA1AAA", recipient=recipient, body=f"m{i+1}"
        )


def test_empty_and_invalid_cursor(database):
    s = MessageStore(database)
    assert s.get_new_messages(callsign="EA2AAA", since=0, limit=20).messages == ()
    with pytest.raises(InvalidCursorError):
        s.get_new_messages(callsign="EA2AAA", since=1, limit=20)


def test_complete_visible_and_private(database):
    s = MessageStore(database)
    seed(s, "EA2AAA", 2)
    seed(s, "EA3AAA", 1)
    p = s.get_new_messages(callsign="EA2AAA", since=0, limit=20)
    assert [(x.sequence, x.recipient, x.body) for x in p.messages] == [
        (1, "EA2AAA", "m1"),
        (2, "EA2AAA", "m2"),
    ]


def test_pagination(database):
    s = MessageStore(database)
    seed(s, "EA2AAA", 5)
    a = s.get_new_messages(callsign="EA2AAA", since=0, limit=2)
    b = s.get_new_messages(callsign="EA2AAA", since=a.next_since, limit=2)
    c = s.get_new_messages(callsign="EA2AAA", since=b.next_since, limit=2)
    assert (
        [x.sequence for x in a.messages],
        [x.sequence for x in b.messages],
        [x.sequence for x in c.messages],
    ) == ([1, 2], [3, 4], [5])
    assert a.has_more and b.has_more and not c.has_more


@pytest.mark.parametrize("limit", [1, 20])
def test_limit_boundaries(database, limit):
    assert (
        MessageStore(database)
        .get_new_messages(callsign="EA2AAA", since=0, limit=limit)
        .messages
        == ()
    )


@pytest.mark.parametrize("limit", [0, 21, True, 1.5])
def test_invalid_limits(database, limit):
    with pytest.raises(ValueError):
        MessageStore(database).get_new_messages(callsign="EA2AAA", since=0, limit=limit)


@pytest.mark.parametrize("since", [-1, 2**32, True, 1.5])
def test_since_u32(database, since):
    with pytest.raises(ValueError):
        MessageStore(database).get_new_messages(callsign="EA2AAA", since=since, limit=1)


def test_restart(database):
    s = MessageStore(database)
    seed(s, "EA2AAA", 2)
    assert [
        x.sequence
        for x in MessageStore(database)
        .get_new_messages(callsign="EA2AAA", since=0, limit=20)
        .messages
    ] == [1, 2]


def test_corrupt_body(database):
    s = MessageStore(database)
    seed(s, "EA2AAA", 1)
    with database.connect() as c:
        c.execute("UPDATE messages SET body=X'FF'")
    with pytest.raises(StorageIntegrityError, match="UTF-8"):
        s.get_new_messages(callsign="EA2AAA", since=0, limit=20)
