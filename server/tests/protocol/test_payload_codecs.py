import pytest

from openqsp.protocol.codec import decode_frame, encode_frame
from openqsp.protocol.constants import AckStatus, ErrorCode, Operation
from openqsp.protocol.errors import InvalidFieldError, PayloadLengthError
from openqsp.protocol.models import (
    Ack,
    Bulletin,
    BulletinHeader,
    End,
    Error,
    GetBulletin,
    GetNewBulletins,
    GetNewMessages,
    Message,
    SendMessage,
)


CANONICAL_VECTORS = [
    ("01 01 00 18 01 02 03 04 05 06 07 08 65 00 00 00 06 45 41 31 41 42 43 04 48 6F 6C 61", SendMessage(0x0102030405060708, 0x65000000, "EA1ABC", "Hola")),
    ("01 44 00 09 01 02 03 04 05 06 07 08 00", Ack(0x0102030405060708, AckStatus.STORED)),
    ("01 02 00 09 00 00 00 00 00 00 00 7C 05", GetNewMessages(124, 5)),
    ("01 40 00 27 00 00 00 00 00 00 00 7D 01 02 03 04 05 06 07 08 65 00 00 00 06 45 41 33 47 4E 55 06 45 41 31 41 42 43 04 48 6F 6C 61", Message(125, 0x0102030405060708, 0x65000000, "EA3GNU", "EA1ABC", "Hola")),
    ("01 43 00 0B 02 01 00 00 00 00 00 00 00 7D 00", End(Operation.GET_NEW_MESSAGES, 1, 125, False)),
    ("01 03 00 09 00 00 00 00 00 00 00 F5 05", GetNewBulletins(245, 5)),
    ("01 41 00 24 00 00 00 00 00 00 00 F6 11 12 13 14 15 16 17 18 65 00 00 00 06 45 41 31 41 42 43 08 54 65 73 74 20 56 48 46", BulletinHeader(246, 0x1112131415161718, 0x65000000, "EA1ABC", "Test VHF")),
    ("01 43 00 0B 03 01 00 00 00 00 00 00 00 F6 00", End(Operation.GET_NEW_BULLETINS, 1, 246, False)),
    ("01 04 00 08 11 12 13 14 15 16 17 18", GetBulletin(0x1112131415161718)),
    ("01 42 00 2E 11 12 13 14 15 16 17 18 65 00 00 00 06 45 41 31 41 42 43 08 54 65 73 74 20 56 48 46 11 41 63 74 69 76 69 64 61 64 20 64 6F 6D 69 6E 67 6F", Bulletin(0x1112131415161718, 0x65000000, "EA1ABC", "Test VHF", "Actividad domingo")),
    ("01 45 00 0C 04 07 09 4E 6F 74 20 66 6F 75 6E 64", Error(Operation.GET_BULLETIN, ErrorCode.NOT_FOUND, "Not found")),
    ("01 43 00 0B 02 00 00 00 00 00 00 00 00 7D 00", End(Operation.GET_NEW_MESSAGES, 0, 125, False)),
]


@pytest.mark.parametrize(("hex_frame", "expected"), CANONICAL_VECTORS)
def test_canonical_vectors_decode_and_encode(hex_frame: str, expected: object) -> None:
    frame = bytes.fromhex(hex_frame)
    assert decode_frame(frame) == expected
    assert encode_frame(expected) == frame  # type: ignore[arg-type]


@pytest.mark.parametrize("maximum", [0, 21])
def test_retrieval_max_outside_limits(maximum: int) -> None:
    frame = bytes((1, Operation.GET_NEW_MESSAGES, 0, 9)) + bytes(8) + bytes((maximum,))
    with pytest.raises(InvalidFieldError, match="max"):
        decode_frame(frame)
    with pytest.raises(InvalidFieldError, match="max"):
        encode_frame(GetNewMessages(0, maximum))


@pytest.mark.parametrize("model", [
    SendMessage(0, 1, "EA1ABC", "x"), GetBulletin(0), Ack(0, AckStatus.STORED),
    Message(0, 1, 1, "EA1ABC", "EA2ABC", "x"),
    BulletinHeader(0, 1, 1, "EA1ABC", "x"),
    SendMessage(1, 0, "EA1ABC", "x"), Bulletin(1, 0, "EA1ABC", "x", "x"),
])
def test_nonzero_numeric_fields_are_enforced_on_encode(model: object) -> None:
    with pytest.raises(InvalidFieldError):
        encode_frame(model)  # type: ignore[arg-type]


@pytest.mark.parametrize("callsign", ["A1", "EA12345678901", "ea1abc", "EA1ABC-7", "ABC", "123"])
def test_invalid_callsigns_are_rejected(callsign: str) -> None:
    with pytest.raises(InvalidFieldError):
        encode_frame(SendMessage(1, 1, callsign, "x"))


@pytest.mark.parametrize("model", [
    SendMessage(1, 1, "EA1ABC", ""),
    BulletinHeader(1, 1, 1, "EA1ABC", ""),
    SendMessage(1, 1, "EA1ABC", "x" * 209),
    BulletinHeader(1, 1, 1, "EA1ABC", "x" * 65),
    Bulletin(1, 1, "EA1ABC", "x", "x" * 165),
    SendMessage(1, 1, "EA1ABC", "a\x00b"),
    Error(0, ErrorCode.INVALID_FRAME, "x" * 65),
])
def test_invalid_text_fields_are_rejected_on_encode(model: object) -> None:
    with pytest.raises(InvalidFieldError):
        encode_frame(model)  # type: ignore[arg-type]


def test_utf8_limits_count_encoded_bytes() -> None:
    accepted = SendMessage(1, 1, "EA1ABC", "é" * 104)
    assert decode_frame(encode_frame(accepted)) == accepted
    with pytest.raises(InvalidFieldError):
        encode_frame(SendMessage(1, 1, "EA1ABC", "é" * 105))


@pytest.mark.parametrize("frame", [
    "01 01 00 10 00 00 00 00 00 00 00 01 00 00 00 01 06 45 41",
    "01 01 00 0E 00 00 00 00 00 00 00 01 00 00 00 01 01 FF",
    "01 01 00 12 00 00 00 00 00 00 00 01 00 00 00 01 06 45 41 31 41 42 43",
    "01 01 00 15 00 00 00 00 00 00 00 01 00 00 00 01 06 45 41 31 41 42 43 01 78 00",
])
def test_truncated_invalid_utf8_missing_and_trailing_payloads(frame: str) -> None:
    with pytest.raises((InvalidFieldError, PayloadLengthError)):
        decode_frame(bytes.fromhex(frame))


def test_unknown_ack_status_and_error_code_are_rejected() -> None:
    with pytest.raises(InvalidFieldError, match="ACK status"):
        decode_frame(bytes.fromhex("01 44 00 09 00 00 00 00 00 00 00 01 FF"))
    with pytest.raises(InvalidFieldError, match="ERROR code"):
        decode_frame(bytes.fromhex("01 45 00 03 00 FF 00"))


def test_end_field_validation() -> None:
    with pytest.raises(InvalidFieldError, match="request_operation"):
        decode_frame(bytes.fromhex("01 43 00 0B 04 00 00 00 00 00 00 00 00 00 00"))
    with pytest.raises(InvalidFieldError, match="has_more"):
        decode_frame(bytes.fromhex("01 43 00 0B 02 00 00 00 00 00 00 00 00 00 02"))


def test_error_allows_unknown_operation_marker_and_empty_detail() -> None:
    model = Error(0, ErrorCode.UNKNOWN_OPERATION, "")
    assert decode_frame(encode_frame(model)) == model
