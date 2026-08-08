import pytest

from openqsp.protocol.codec import decode_frame, encode_frame
from openqsp.protocol.constants import ErrorCode, Operation
from openqsp.protocol.errors import (
    InvalidFieldError, PayloadLengthError, UnknownOperationError,
    UnsupportedVersionError,
)
from openqsp.protocol.models import (
    Bulletin,
    BulletinHeader,
    End,
    Error,
    GetBulletin,
    GetNewBulletins,
    GetNewMessages,
    Message,
    SendMessage,
    Stored,
)


CANONICAL_VECTORS = [
    ("01 01 00 10 65 00 00 00 06 45 41 31 41 42 43 04 48 6F 6C 61", SendMessage(0x65000000, "EA1ABC", "Hola")),
    ("01 44 00 00", Stored()),
    ("01 02 00 05 00 00 00 7C 05", GetNewMessages(124, 5)),
    ("01 40 00 1B 00 00 00 7D 65 00 00 00 06 45 41 33 47 4E 55 06 45 41 31 41 42 43 04 48 6F 6C 61", Message(125, 0x65000000, "EA3GNU", "EA1ABC", "Hola")),
    ("01 43 00 07 02 01 00 00 00 7D 00", End(Operation.GET_NEW_MESSAGES, 1, 125, False)),
    ("01 03 00 05 00 00 00 F5 05", GetNewBulletins(245, 5)),
    ("01 41 00 18 00 00 00 F6 65 00 00 00 06 45 41 31 41 42 43 08 54 65 73 74 20 56 48 46", BulletinHeader(246, 0x65000000, "EA1ABC", "Test VHF")),
    ("01 43 00 07 03 01 00 00 00 F6 00", End(Operation.GET_NEW_BULLETINS, 1, 246, False)),
    ("01 04 00 04 00 00 00 F6", GetBulletin(246)),
    ("01 42 00 2A 00 00 00 F6 65 00 00 00 06 45 41 31 41 42 43 08 54 65 73 74 20 56 48 46 11 41 63 74 69 76 69 64 61 64 20 64 6F 6D 69 6E 67 6F", Bulletin(246, 0x65000000, "EA1ABC", "Test VHF", "Actividad domingo")),
    ("01 45 00 0C 04 07 09 4E 6F 74 20 66 6F 75 6E 64", Error(Operation.GET_BULLETIN, ErrorCode.NOT_FOUND, "Not found")),
    ("01 43 00 07 02 00 00 00 00 7D 00", End(Operation.GET_NEW_MESSAGES, 0, 125, False)),
]

@pytest.mark.parametrize(("hex_frame", "expected"), CANONICAL_VECTORS)
def test_canonical_vectors_decode_and_encode(hex_frame: str, expected: object) -> None:
    frame = bytes.fromhex(hex_frame)
    assert decode_frame(frame) == expected
    assert encode_frame(expected) == frame  # type: ignore[arg-type]


@pytest.mark.parametrize("maximum", [0, 21])
def test_retrieval_max_outside_limits(maximum: int) -> None:
    frame = bytes((1, Operation.GET_NEW_MESSAGES, 0, 5)) + bytes(4) + bytes((maximum,))
    with pytest.raises(InvalidFieldError, match="max"):
        decode_frame(frame)
    with pytest.raises(InvalidFieldError, match="max"):
        encode_frame(GetNewMessages(0, maximum))


@pytest.mark.parametrize("model", [
    GetBulletin(0), Message(0, 1, "EA1ABC", "EA2ABC", "x"),
    BulletinHeader(0, 1, "EA1ABC", "x"),
    SendMessage(0, "EA1ABC", "x"), Bulletin(1, 0, "EA1ABC", "x", "x"),
])
def test_nonzero_numeric_fields_are_enforced_on_encode(model: object) -> None:
    with pytest.raises(InvalidFieldError):
        encode_frame(model)  # type: ignore[arg-type]


@pytest.mark.parametrize("callsign", ["A1", "EA12345678901", "ea1abc", "EA1ABC-7", "ABC", "123"])
def test_invalid_callsigns_are_rejected(callsign: str) -> None:
    with pytest.raises(InvalidFieldError):
        encode_frame(SendMessage(1, callsign, "x"))


@pytest.mark.parametrize("model", [
    SendMessage(1, "EA1ABC", ""),
    BulletinHeader(1, 1, "EA1ABC", ""),
    SendMessage(1, "EA1ABC", "x" * 209),
    BulletinHeader(1, 1, "EA1ABC", "x" * 65),
    Bulletin(1, 1, "EA1ABC", "x", "x" * 165),
    SendMessage(1, "EA1ABC", "a\x00b"),
    Error(0, ErrorCode.INVALID_FRAME, "x" * 65),
])
def test_invalid_text_fields_are_rejected_on_encode(model: object) -> None:
    with pytest.raises(InvalidFieldError):
        encode_frame(model)  # type: ignore[arg-type]


def test_utf8_limits_count_encoded_bytes() -> None:
    accepted = SendMessage(1, "EA1ABC", "é" * 104)
    assert decode_frame(encode_frame(accepted)) == accepted
    with pytest.raises(InvalidFieldError):
        encode_frame(SendMessage(1, "EA1ABC", "é" * 105))


@pytest.mark.parametrize("frame", [
    "01 01 00 10 00 00 00 00 00 00 00 01 00 00 00 01 06 45 41",
    "01 01 00 0E 00 00 00 00 00 00 00 01 00 00 00 01 01 FF",
    "01 01 00 12 00 00 00 00 00 00 00 01 00 00 00 01 06 45 41 31 41 42 43",
    "01 01 00 15 00 00 00 00 00 00 00 01 00 00 00 01 06 45 41 31 41 42 43 01 78 00",
])
def test_truncated_invalid_utf8_missing_and_trailing_payloads(frame: str) -> None:
    with pytest.raises((InvalidFieldError, PayloadLengthError)):
        decode_frame(bytes.fromhex(frame))


def test_stored_rejects_old_ack_payload_and_unknown_error_code() -> None:
    with pytest.raises(PayloadLengthError, match="STORED"):
        decode_frame(bytes.fromhex("01 44 00 09 00 00 00 00 00 00 00 01 FF"))
    with pytest.raises(InvalidFieldError, match="ERROR code"):
        decode_frame(bytes.fromhex("01 45 00 03 00 FF 00"))


def test_end_field_validation() -> None:
    with pytest.raises(InvalidFieldError, match="request_operation"):
        decode_frame(bytes.fromhex("01 43 00 07 04 00 00 00 00 00 00"))
    with pytest.raises(InvalidFieldError, match="has_more"):
        decode_frame(bytes.fromhex("01 43 00 07 02 00 00 00 00 00 02"))


def test_error_allows_unknown_operation_marker_and_empty_detail() -> None:
    model = Error(0, ErrorCode.UNKNOWN_OPERATION, "")
    assert decode_frame(encode_frame(model)) == model


def frame(operation: Operation, payload: bytes) -> bytes:
    return bytes((1, operation, 0, len(payload))) + payload


def send(*, created_at=1, recipient=b"EA1ABC", body=b"x") -> bytes:
    return (created_at.to_bytes(4, "big")
            + bytes([len(recipient)]) + recipient + bytes([len(body)]) + body)


def message(*, sequence=1, created_at=1, author=b"EA1ABC",
            recipient=b"EA2ABC", body=b"x") -> bytes:
    return (sequence.to_bytes(4, "big") + created_at.to_bytes(4, "big") + bytes([len(author)]) + author
            + bytes([len(recipient)]) + recipient + bytes([len(body)]) + body)


def header(*, sequence=1, created_at=1, author=b"EA1ABC", title=b"x") -> bytes:
    return (sequence.to_bytes(4, "big") + created_at.to_bytes(4, "big") + bytes([len(author)]) + author
            + bytes([len(title)]) + title)


def bulletin(*, sequence=1, created_at=1, author=b"EA1ABC", title=b"x", body=b"x") -> bytes:
    return (sequence.to_bytes(4, "big") + created_at.to_bytes(4, "big")
            + bytes([len(author)]) + author + bytes([len(title)]) + title
            + bytes([len(body)]) + body)


@pytest.mark.parametrize(("raw", "error"), [
    ("02 04 00 08 11 12 13 14 15 16 17 18", UnsupportedVersionError),
    ("01 04 01 08 11 12 13 14 15 16 17 18", InvalidFieldError),
    ("01 04 00 08 11 12 13 14", PayloadLengthError),
    ("01 04 00 08 11 12 13 14 15 16 17 18 FF", PayloadLengthError),
    ("01 02 00 05 00 00 00 7C 00", InvalidFieldError),
    ("01 01 00 18 00 00 00 00 00 00 00 00 65 00 00 00 06 45 41 31 41 42 43 04 48 6F 6C 61", InvalidFieldError),
    ("01 01 00 14 01 02 03 04 05 06 07 08 65 00 00 00 06 45 41 31 41 42 43 00", InvalidFieldError),
    ("01 01 00 1B 01 02 03 04 05 06 07 08 65 00 00 00 09 45 41 31 41 42 43 2D 31 30 04 48 6F 6C 61", InvalidFieldError),
    ("01 01 00 16 01 02 03 04 05 06 07 08 65 00 00 00 06 45 41 31 41 42 43 02 C3 28", InvalidFieldError),
    ("01 7F 00 00", UnknownOperationError),
])
def test_all_documented_invalid_vectors(raw: str, error: type[Exception]) -> None:
    with pytest.raises(error):
        decode_frame(bytes.fromhex(raw))


@pytest.mark.parametrize(("operation", "payload"), [
    (Operation.SEND_MESSAGE, send(created_at=0)),
    (Operation.MESSAGE, message(sequence=0)),
    (Operation.MESSAGE, message(created_at=0)),
    (Operation.BULLETIN_HEADER, header(sequence=0)),
    (Operation.BULLETIN_HEADER, header(created_at=0)),
    (Operation.BULLETIN, bulletin(sequence=0)),
    (Operation.BULLETIN, bulletin(created_at=0)),
])
def test_decode_enforces_nonzero_numeric_fields(operation: Operation, payload: bytes) -> None:
    with pytest.raises(InvalidFieldError):
        decode_frame(frame(operation, payload))


@pytest.mark.parametrize("value", [b"ea1abc", b"A1", b"EA12345678901", b"EA1ABC-7",
                                   b"EA1.ABC", b"ABC", b"123", b"EA1\xffBC"])
def test_decode_rejects_invalid_callsigns(value: bytes) -> None:
    with pytest.raises(InvalidFieldError):
        decode_frame(frame(Operation.SEND_MESSAGE, send(recipient=value)))


@pytest.mark.parametrize("value", [b"A1B", b"EA1234567890"])
def test_callsign_boundaries(value: bytes) -> None:
    assert decode_frame(frame(Operation.SEND_MESSAGE, send(recipient=value))).recipient == value.decode()


@pytest.mark.parametrize(("operation", "payload"), [
    (Operation.SEND_MESSAGE, send(body=b"")),
    (Operation.SEND_MESSAGE, send(body=b"x" * 209)),
    (Operation.SEND_MESSAGE, send(body=b"\xc3\x28")),
    (Operation.SEND_MESSAGE, send(body=b"a\0b")),
    (Operation.BULLETIN_HEADER, header(title=b"")),
    (Operation.BULLETIN_HEADER, header(title=b"x" * 65)),
    (Operation.BULLETIN_HEADER, header(title=b"\xff")),
    (Operation.BULLETIN_HEADER, header(title=b"a\0b")),
    (Operation.BULLETIN, bulletin(body=b"")),
    (Operation.BULLETIN, bulletin(body=b"x" * 165)),
])
def test_decode_enforces_wire_text_rules(operation: Operation, payload: bytes) -> None:
    with pytest.raises(InvalidFieldError):
        decode_frame(frame(operation, payload))


@pytest.mark.parametrize(("operation", "payload", "attribute"), [
    (Operation.SEND_MESSAGE, send(body=b"x"), "body"),
    (Operation.SEND_MESSAGE, send(body=b"x" * 208), "body"),
    (Operation.SEND_MESSAGE, send(body="é".encode() * 104), "body"),
    (Operation.BULLETIN_HEADER, header(title=b"x"), "title"),
    (Operation.BULLETIN_HEADER, header(title=b"x" * 64), "title"),
    (Operation.BULLETIN_HEADER, header(title="é".encode() * 32), "title"),
    (Operation.BULLETIN, bulletin(body=b"x"), "body"),
    (Operation.BULLETIN, bulletin(body=b"x" * 164), "body"),
    (Operation.BULLETIN, bulletin(body="é".encode() * 82), "body"),
])
def test_text_exact_byte_boundaries(operation, payload, attribute) -> None:
    assert getattr(decode_frame(frame(operation, payload)), attribute)


def test_multibyte_text_beyond_byte_limit_is_rejected() -> None:
    with pytest.raises(InvalidFieldError):
        decode_frame(frame(Operation.SEND_MESSAGE, send(body="é".encode() * 105)))


@pytest.mark.parametrize("payload", [
    bytes.fromhex("00 00 00 00 00 00 00 01 00 00 00 01 06 45 41"),
    bytes.fromhex("00 00 00 00 00 00 00 01 00 00 00 01 05 45 41 31 41 42 43 01 78"),
    bytes.fromhex("00 00 00 00 00 00 00 01 00 00 00 01 07 45 41 31 41 42 43 01 78"),
    send() + b"\xff",
])
def test_length_prefixes_partition_payload_exactly(payload: bytes) -> None:
    with pytest.raises((InvalidFieldError, PayloadLengthError)):
        decode_frame(frame(Operation.SEND_MESSAGE, payload))


@pytest.mark.parametrize("maximum", [1, 20])
def test_retrieval_max_boundaries(maximum: int) -> None:
    for model in (GetNewMessages(0, maximum), GetNewBulletins(2**32 - 1, maximum)):
        assert decode_frame(encode_frame(model)) == model


@pytest.mark.parametrize("operation", [Operation.GET_NEW_MESSAGES, Operation.GET_NEW_BULLETINS])
@pytest.mark.parametrize("count", [0, 255])
@pytest.mark.parametrize("has_more", [False, True])
def test_end_boundaries(operation: Operation, count: int, has_more: bool) -> None:
    model = End(operation, count, 2**32 - 1, has_more)
    assert decode_frame(encode_frame(model)) == model


@pytest.mark.parametrize("request_operation", [Operation.SEND_MESSAGE, Operation.END, 0x7f])
def test_end_rejects_invalid_request_operation(request_operation: int) -> None:
    with pytest.raises(InvalidFieldError):
        decode_frame(frame(Operation.END, bytes([request_operation, 0]) + bytes(5)))


@pytest.mark.parametrize("code", list(ErrorCode))
def test_all_error_codes(code: ErrorCode) -> None:
    model = Error(Operation.GET_NEW_MESSAGES, code, "á")
    assert decode_frame(encode_frame(model)) == model


@pytest.mark.parametrize("detail", ["", "é", "x" * 64])
def test_error_detail_boundaries(detail: str) -> None:
    model = Error(0, ErrorCode.INVALID_FRAME, detail)
    assert decode_frame(encode_frame(model)) == model


@pytest.mark.parametrize("detail", [b"x" * 65, b"\xff", b"a\0b"])
def test_error_rejects_invalid_detail(detail: bytes) -> None:
    payload = bytes([Operation.GET_BULLETIN, ErrorCode.INVALID_FIELD, len(detail)]) + detail
    with pytest.raises(InvalidFieldError):
        decode_frame(frame(Operation.ERROR, payload))


def test_error_rejects_unknown_nonzero_request_operation() -> None:
    with pytest.raises(InvalidFieldError):
        decode_frame(frame(Operation.ERROR, b"\x7f\x01\x00"))


def test_unsigned_extremes_and_permitted_zero() -> None:
    models = [SendMessage(2**32 - 1, "EA1ABC", "x"), GetNewMessages(0, 1),
              GetNewMessages(2**32 - 1, 1),
              End(Operation.GET_NEW_MESSAGES, 0, 0, False)]
    for model in models:
        assert decode_frame(encode_frame(model)) == model


@pytest.mark.parametrize("sequence", [1, 2**32 - 1])
def test_object_sequence_boundaries(sequence: int) -> None:
    models = [
        Message(sequence, 1, "EA1ABC", "EA2ABC", "x"),
        BulletinHeader(sequence, 1, "EA1ABC", "x"),
        Bulletin(sequence, 1, "EA1ABC", "x", "x"),
        GetBulletin(sequence),
    ]
    for model in models:
        assert decode_frame(encode_frame(model)) == model


@pytest.mark.parametrize("model", [
    GetNewMessages(2**32, 1), End(Operation.GET_NEW_MESSAGES, 0, 2**32, False),
    Message(2**32, 1, "EA1ABC", "EA2ABC", "x"), GetBulletin(2**32),
])
def test_u32_values_above_range_are_rejected(model: object) -> None:
    with pytest.raises(InvalidFieldError):
        encode_frame(model)  # type: ignore[arg-type]
