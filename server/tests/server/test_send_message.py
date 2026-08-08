from unittest.mock import Mock
import pytest
from openqsp.protocol import *
from openqsp.storage import *
from openqsp.server import ServerCore


def db(tmp_path):
    d = Database(tmp_path / "x.db")
    d.initialize()
    return d


def response(core, obj, user="K1ABC"):
    return decode_frame(core.handle_frame(user, encode_frame(obj))[0])


def test_valid_stored_authenticated_author(tmp_path):
    d = db(tmp_path)
    s = MessageStore(d, clock=lambda: 2000)
    request = SendMessage(1234, "EA3GNU", "hello")
    assert response(ServerCore(message_store=s), request) == Stored()
    m = s.get_new_messages(callsign="EA3GNU", since=0, limit=20).messages[0]
    assert (m.sequence, m.created_at, m.author, m.recipient, m.body) == (
        1,
        1234,
        "K1ABC",
        "EA3GNU",
        "hello",
    )


def test_each_send_is_new_application_object(tmp_path):
    d = db(tmp_path)
    s = MessageStore(d)
    c = ServerCore(message_store=s)
    r = SendMessage(1, "EA3GNU", "same")
    assert response(c, r) == Stored()
    assert response(c, r) == Stored()
    assert [
        x.sequence
        for x in s.get_new_messages(callsign="EA3GNU", since=0, limit=20).messages
    ] == [1, 2]


def test_bulletin_and_mailbox_sequences_are_independent(tmp_path):
    d = db(tmp_path)
    BulletinStore(d).store_bulletin(created_at=1, author="EA1AAA", title="t", body="b")
    s = MessageStore(d)
    assert (
        response(ServerCore(message_store=s), SendMessage(1, "EA3GNU", "m")) == Stored()
    )
    assert (
        s.get_new_messages(callsign="EA3GNU", since=0, limit=20).messages[0].sequence
        == 1
    )


def test_restart_allocates_next_sequence(tmp_path):
    d = db(tmp_path)
    c = ServerCore(message_store=MessageStore(d))
    assert response(c, SendMessage(1, "EA3GNU", "a")) == Stored()
    d.initialize()
    assert (
        response(
            ServerCore(message_store=MessageStore(d)), SendMessage(2, "EA3GNU", "b")
        )
        == Stored()
    )
    assert [
        x.sequence
        for x in MessageStore(d)
        .get_new_messages(callsign="EA3GNU", since=0, limit=20)
        .messages
    ] == [1, 2]


def test_malformed_send_uses_error():
    out = ServerCore().handle_frame("K1ABC", b"\x01\x01\x00\x03\x00\x00\x00")
    assert isinstance(decode_frame(out[0]), Error)


def test_missing_store_busy():
    assert (
        response(ServerCore(), SendMessage(1, "EA3GNU", "x")).error_code
        == ErrorCode.BUSY
    )


@pytest.mark.parametrize("callsign", ["bad", "ea1abc", "ABC"])
def test_invalid_authenticated_callsign(tmp_path, callsign):
    assert (
        response(
            ServerCore(message_store=MessageStore(db(tmp_path))),
            SendMessage(1, "EA3GNU", "x"),
            callsign,
        ).error_code
        == ErrorCode.UNAUTHORIZED
    )


@pytest.mark.parametrize(
    "error,code",
    [
        (SequenceExhaustedError(), ErrorCode.BUSY),
        (StorageIntegrityError(), ErrorCode.INTERNAL_ERROR),
    ],
)
def test_storage_failures(error, code):
    s = Mock()
    s.store_message.side_effect = error
    assert (
        response(ServerCore(message_store=s), SendMessage(1, "EA3GNU", "x")).error_code
        == code
    )
