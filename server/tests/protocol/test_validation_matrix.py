"""Broad boundary matrix retained as protocol regression coverage."""

import pytest
from openqsp.protocol import *
from openqsp.protocol.errors import InvalidFieldError, PayloadLengthError

INVALID_CALLSIGNS = (
    [
        "",
        "A",
        "AB",
        "ABC",
        "123",
        "ea1abc",
        "EA-1",
        "EA_1",
        "EA 1",
        "ÉA1",
        "A1!",
        "A1/",
        "A1.",
        "A1:",
        "A1+",
        "A1=",
        "A1?",
        "A1@",
        "A1[",
        "A1]",
        "1aA",
        "a1A",
        "AAa1",
        "A" * 13 + "1",
        "1" * 13 + "A",
        "\x00A1",
        " A1",
        "A1 ",
    ]
    + [f"A1{chr(code)}" for code in range(33, 48)]
    + [f"A1{chr(code)}" for code in range(58, 65)]
)


@pytest.mark.parametrize("callsign", INVALID_CALLSIGNS)
def test_invalid_recipient_callsign_matrix(callsign):
    with pytest.raises(InvalidFieldError):
        encode_frame(SendMessage(1, callsign, "x"))


@pytest.mark.parametrize("callsign", INVALID_CALLSIGNS)
def test_invalid_author_callsign_matrix(callsign):
    with pytest.raises(InvalidFieldError):
        encode_frame(Message(1, 1, callsign, "EA1ABC", "x"))


@pytest.mark.parametrize("length", list(range(0, 1)) + list(range(209, 250)))
def test_message_body_length_matrix(length):
    with pytest.raises(InvalidFieldError):
        encode_frame(SendMessage(1, "EA1ABC", "x" * length))


@pytest.mark.parametrize("length", list(range(0, 1)) + list(range(65, 90)))
def test_bulletin_title_length_matrix(length):
    with pytest.raises(InvalidFieldError):
        encode_frame(Bulletin(1, 1, "EA1ABC", "x" * length, "b"))


@pytest.mark.parametrize("length", list(range(0, 1)) + list(range(165, 190)))
def test_bulletin_body_length_matrix(length):
    with pytest.raises(InvalidFieldError):
        encode_frame(Bulletin(1, 1, "EA1ABC", "t", "x" * length))


@pytest.mark.parametrize(
    "value",
    [-1, 2**32, 2**32 + 1, 2**40, 2**63, 2**64 - 1, True, False, 1.0, "1", None],
)
@pytest.mark.parametrize(
    "factory",
    [
        lambda v: GetNewMessages(v, 1),
        lambda v: GetNewBulletins(v, 1),
        lambda v: Message(v, 1, "EA1ABC", "EA2ABC", "x"),
        lambda v: Bulletin(v, 1, "EA1ABC", "t", "b"),
    ],
)
def test_u32_matrix(value, factory):
    with pytest.raises(InvalidFieldError):
        encode_frame(factory(value))


@pytest.mark.parametrize("cut", range(4, 24))
def test_truncated_message_matrix(cut):
    wire = encode_frame(Message(1, 1, "EA1ABC", "EA2ABC", "hello"))
    candidate = wire[:cut]
    if len(candidate) >= 4:
        candidate = candidate[:3] + bytes((wire[3],)) + candidate[4:]
    with pytest.raises(PayloadLengthError):
        decode_frame(candidate)
