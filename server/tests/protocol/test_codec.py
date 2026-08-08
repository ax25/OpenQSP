import pytest

from openqsp.protocol import codec
from openqsp.protocol.codec import decode_frame, encode_frame
from openqsp.protocol.constants import MAX_FRAME_SIZE, Operation
from openqsp.protocol.errors import (
    InvalidFieldError,
    PayloadLengthError,
    ProtocolDecodeError,
    ProtocolEncodeError,
    UnknownOperationError,
    UnsupportedVersionError,
)
from openqsp.protocol.models import GetBulletin, GetNewMessages


GET_BULLETIN_FRAME = bytes.fromhex(
    "01 04 00 08 11 12 13 14 15 16 17 18"
)


def test_valid_header_and_operation_payload_dispatch() -> None:
    assert decode_frame(GET_BULLETIN_FRAME) == GetBulletin(0x1112131415161718)


def test_encode_frame_reproduces_canonical_get_bulletin_vector() -> None:
    assert encode_frame(GetBulletin(0x1112131415161718)) == GET_BULLETIN_FRAME


@pytest.mark.parametrize("frame", [b"", b"\x01", b"\x01\x04", b"\x01\x04\x00"])
def test_frame_too_short_for_header(frame: bytes) -> None:
    with pytest.raises(PayloadLengthError):
        decode_frame(frame)


def test_unknown_version_uses_specific_exception() -> None:
    with pytest.raises(UnsupportedVersionError):
        decode_frame(bytes.fromhex("02 04 00 08 11 12 13 14 15 16 17 18"))


def test_unknown_operation_uses_specific_exception() -> None:
    with pytest.raises(UnknownOperationError):
        decode_frame(bytes.fromhex("01 FF 00 00"))


def test_nonzero_version_01_flags_are_invalid() -> None:
    with pytest.raises(InvalidFieldError):
        decode_frame(bytes.fromhex("01 04 01 08 11 12 13 14 15 16 17 18"))


def test_declared_payload_larger_than_available_bytes() -> None:
    with pytest.raises(PayloadLengthError, match="8 declared, 7 present"):
        decode_frame(bytes.fromhex("01 04 00 08 11 12 13 14 15 16 17"))


def test_declared_payload_smaller_than_available_bytes() -> None:
    with pytest.raises(PayloadLengthError, match="7 declared, 8 present"):
        decode_frame(bytes.fromhex("01 04 00 07 11 12 13 14 15 16 17 18"))


def test_maximum_payload_reaches_operation_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = bytes(range(255))
    seen: list[bytes] = []

    def decode_max(candidate: bytes) -> GetBulletin:
        seen.append(candidate)
        return GetBulletin(1)

    monkeypatch.setitem(codec._DECODERS, Operation.GET_BULLETIN, decode_max)

    assert decode_frame(bytes((1, Operation.GET_BULLETIN, 0, 255)) + payload) == GetBulletin(1)
    assert seen == [payload]


def test_frame_over_maximum_is_rejected_before_dispatch() -> None:
    oversized = bytes((1, Operation.GET_BULLETIN, 0, 255)) + bytes(256)
    assert len(oversized) == MAX_FRAME_SIZE + 1
    with pytest.raises(PayloadLengthError, match="maximum"):
        decode_frame(oversized)


def test_known_operation_without_m1_3_payload_codec_is_explicit() -> None:
    with pytest.raises(ProtocolDecodeError, match="deferred to M1.3"):
        decode_frame(bytes.fromhex("01 02 00 09 00 00 00 00 00 00 00 7C 05"))


def test_encode_without_m1_3_payload_codec_is_explicit() -> None:
    with pytest.raises(ProtocolEncodeError, match="deferred to M1.3"):
        encode_frame(GetNewMessages(since=124, max=5))


def test_payload_codec_validates_required_length_after_common_header() -> None:
    with pytest.raises(PayloadLengthError, match="exactly 8 bytes"):
        decode_frame(bytes.fromhex("01 04 00 07 11 12 13 14 15 16 17"))


def test_payload_codec_rejects_zero_identifier() -> None:
    with pytest.raises(InvalidFieldError, match="non-zero"):
        decode_frame(bytes.fromhex("01 04 00 08 00 00 00 00 00 00 00 00"))


def test_decode_accepts_bytes_only() -> None:
    with pytest.raises(ProtocolDecodeError, match="must be bytes"):
        decode_frame(bytearray(GET_BULLETIN_FRAME))  # type: ignore[arg-type]
