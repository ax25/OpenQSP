import pytest
from openqsp.protocol import *
from openqsp.protocol.constants import *
from openqsp.protocol.errors import *


def frame(op, payload=b"", flags=0):
    return bytes((1, op, flags, len(payload))) + payload


def prefix(x):
    return bytes((len(x),)) + x


def payload(obj):
    return encode_frame(obj)[4:]


VECTORS = [
    (
        SendMessage(0x65000000, "EA1ABC", "Hola"),
        frame(1, bytes.fromhex("650000000645413141424304486f6c61")),
    ),
    (GetNewMessages(124, 5), frame(2, bytes.fromhex("0000007c05"))),
    (GetNewBulletins(125, 6), frame(3, bytes.fromhex("0000007d06"))),
    (GetBulletin(3), frame(4, bytes.fromhex("00000003"))),
    (
        Message(1, 2, "EA1ABC", "EA3GNU", "x"),
        frame(
            64,
            bytes.fromhex("0000000100000002")
            + prefix(b"EA1ABC")
            + prefix(b"EA3GNU")
            + prefix(b"x"),
        ),
    ),
    (
        BulletinHeader(1, 2, "EA1ABC", "t"),
        frame(65, bytes.fromhex("0000000100000002") + prefix(b"EA1ABC") + prefix(b"t")),
    ),
    (
        Bulletin(1, 2, "EA1ABC", "t", "b"),
        frame(
            66,
            bytes.fromhex("0000000100000002")
            + prefix(b"EA1ABC")
            + prefix(b"t")
            + prefix(b"b"),
        ),
    ),
    (
        End(Operation.GET_NEW_MESSAGES, 1, 3, False),
        frame(67, bytes.fromhex("02010000000300")),
    ),
    (Stored(), frame(68)),
    (
        Error(Operation.GET_BULLETIN, ErrorCode.NOT_FOUND, "no"),
        frame(69, bytes.fromhex("0407026e6f")),
    ),
]


@pytest.mark.parametrize("obj,wire", VECTORS)
def test_canonical_round_trip(obj, wire):
    assert encode_frame(obj) == wire and decode_frame(wire) == obj


@pytest.mark.parametrize(
    "obj",
    [
        GetNewMessages(2**32, 1),
        GetNewBulletins(-1, 1),
        GetBulletin(0),
        Message(0, 1, "EA1ABC", "EA2ABC", "x"),
        BulletinHeader(2**32, 1, "EA1ABC", "x"),
    ],
)
def test_u32_validation(obj):
    with pytest.raises(InvalidFieldError):
        encode_frame(obj)


@pytest.mark.parametrize(
    "obj",
    [
        SendMessage(0, "EA1ABC", "x"),
        SendMessage(1, "bad", "x"),
        SendMessage(1, "EA1ABC", ""),
        SendMessage(1, "EA1ABC", "x" * 209),
        Bulletin(1, 1, "EA1ABC", "", "x"),
        Bulletin(1, 1, "EA1ABC", "x", ""),
    ],
)
def test_field_validation(obj):
    with pytest.raises(InvalidFieldError):
        encode_frame(obj)


@pytest.mark.parametrize(
    "wire",
    [
        frame(68, b"\0"),
        frame(4, b"\0" * 3),
        frame(2, b"\0" * 4),
        frame(67, b"\2\0\0\0\0\0\2"),
    ],
)
def test_exact_payload_lengths(wire):
    with pytest.raises((PayloadLengthError, InvalidFieldError)):
        decode_frame(wire)


def test_stored_is_zero_payload():
    assert encode_frame(Stored()) == b"\x01\x44\x00\x00"
