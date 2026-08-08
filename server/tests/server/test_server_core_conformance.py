from openqsp.protocol import *
from openqsp.storage import *
from openqsp.server import ServerCore


def node(path):
    d = Database(path)
    d.initialize()
    b = BulletinStore(d)
    return ServerCore(message_store=MessageStore(d), bulletin_store=b), b


def exchange(c, user, obj):
    return [decode_frame(x) for x in c.handle_frame(user, encode_frame(obj))]


def test_mailbox_local_identity_privacy(tmp_path):
    c, _ = node(tmp_path / "x")
    for user, to, body in [
        ("EA1AAA", "EA3GNU", "a"),
        ("EA1BBB", "EA3GNU", "b"),
        ("EA1AAA", "EA2GNU", "c"),
    ]:
        assert exchange(c, user, SendMessage(1, to, body)) == [Stored()]
    assert [x.sequence for x in exchange(c, "EA3GNU", GetNewMessages(0, 20))[:-1]] == [
        1,
        2,
    ]
    assert [x.sequence for x in exchange(c, "EA2GNU", GetNewMessages(0, 20))[:-1]] == [
        1
    ]
    assert exchange(c, "EA4GNU", GetNewMessages(0, 20)) == [
        End(Operation.GET_NEW_MESSAGES, 0, 0, False)
    ]


def test_incremental_pagination(tmp_path):
    c, _ = node(tmp_path / "x")
    for i in range(4):
        exchange(c, "EA1AAA", SendMessage(i + 1, "EA3GNU", str(i)))
    a = exchange(c, "EA3GNU", GetNewMessages(0, 2))
    b = exchange(c, "EA3GNU", GetNewMessages(a[-1].next_since, 2))
    assert [x.sequence for x in a[:-1]] == [1, 2] and a[-1].has_more
    assert [x.sequence for x in b[:-1]] == [3, 4]


def test_bulletin_sequence_identity(tmp_path):
    c, b = node(tmp_path / "x")
    b.store_bulletin(created_at=1, author="EA1AAA", title="t", body="body")
    assert exchange(c, "EA3GNU", GetNewBulletins(0, 20))[0] == BulletinHeader(
        1, 1, "EA1AAA", "t"
    )
    assert exchange(c, "EA3GNU", GetBulletin(1)) == [
        Bulletin(1, 1, "EA1AAA", "t", "body")
    ]


def test_restart(tmp_path):
    p = tmp_path / "x"
    c, b = node(p)
    exchange(c, "EA1AAA", SendMessage(1, "EA3GNU", "a"))
    b.store_bulletin(created_at=1, author="EA1AAA", title="t", body="b")
    c, _ = node(p)
    assert exchange(c, "EA3GNU", GetNewMessages(0, 20))[0].sequence == 1
    assert isinstance(exchange(c, "EA3GNU", GetBulletin(1))[0], Bulletin)


def test_malformed_then_healthy(tmp_path):
    c, _ = node(tmp_path / "x")
    assert c.handle_frame("EA1AAA", b"\x01\x02\x00") == []
    assert exchange(c, "EA1AAA", SendMessage(1, "EA3GNU", "ok")) == [Stored()]
