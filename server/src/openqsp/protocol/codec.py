"""Transport-independent OpenQSP Core version 0.1 frame codec.

M1.2 owns common framing and the payload-codec dispatch boundary.  Operation
payload codecs are added to the dispatch tables as they are implemented.
"""

from collections.abc import Callable
from typing import TypeAlias, cast

from .constants import HEADER_SIZE, MAX_FRAME_SIZE, PROTOCOL_VERSION, Operation
from .errors import (
    InvalidFieldError,
    PayloadLengthError,
    ProtocolDecodeError,
    ProtocolEncodeError,
    UnknownOperationError,
    UnsupportedVersionError,
)
from .models import (
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

ProtocolObject: TypeAlias = (
    SendMessage
    | GetNewMessages
    | GetNewBulletins
    | GetBulletin
    | Message
    | BulletinHeader
    | Bulletin
    | End
    | Ack
    | Error
)

PayloadDecoder: TypeAlias = Callable[[bytes], ProtocolObject]
PayloadEncoder: TypeAlias = Callable[[ProtocolObject], bytes]


def _decode_get_bulletin(payload: bytes) -> GetBulletin:
    if len(payload) != 8:
        raise PayloadLengthError("GET_BULLETIN payload must be exactly 8 bytes")
    bulletin_id = int.from_bytes(payload, "big")
    if bulletin_id == 0:
        raise InvalidFieldError("bulletin_id must be non-zero")
    return GetBulletin(bulletin_id=bulletin_id)


def _encode_get_bulletin(obj: ProtocolObject) -> bytes:
    request = cast(GetBulletin, obj)
    if not isinstance(request.bulletin_id, int) or isinstance(request.bulletin_id, bool):
        raise InvalidFieldError("bulletin_id must be an integer")
    if not 0 < request.bulletin_id <= 0xFFFFFFFFFFFFFFFF:
        raise InvalidFieldError("bulletin_id must be a non-zero unsigned 64-bit value")
    return request.bulletin_id.to_bytes(8, "big")


# M1.3 extends these tables with the remaining nine operation payload codecs.
_DECODERS: dict[Operation, PayloadDecoder] = {
    Operation.GET_BULLETIN: _decode_get_bulletin,
}
_ENCODERS: dict[type[object], tuple[Operation, PayloadEncoder]] = {
    GetBulletin: (Operation.GET_BULLETIN, _encode_get_bulletin),
}


def _decode_header(data: bytes) -> tuple[Operation, bytes]:
    """Validate the complete common frame and return operation and payload."""
    if not isinstance(data, bytes):
        raise ProtocolDecodeError("a Core frame must be bytes")
    if len(data) < HEADER_SIZE:
        raise PayloadLengthError("frame is too short to contain the Core header")
    if len(data) > MAX_FRAME_SIZE:
        raise PayloadLengthError("frame exceeds the version 0.1 maximum size")

    version, operation_code, flags, payload_length = data[:HEADER_SIZE]
    if version != PROTOCOL_VERSION:
        raise UnsupportedVersionError(f"unsupported protocol version: 0x{version:02x}")
    try:
        operation = Operation(operation_code)
    except ValueError:
        raise UnknownOperationError(
            f"unknown version 0.1 operation: 0x{operation_code:02x}"
        ) from None
    if flags != 0:
        raise InvalidFieldError("version 0.1 flags must be 0x00")

    actual_payload_length = len(data) - HEADER_SIZE
    if actual_payload_length != payload_length:
        raise PayloadLengthError(
            "declared payload length does not match the complete frame "
            f"({payload_length} declared, {actual_payload_length} present)"
        )
    return operation, data[HEADER_SIZE:]


def decode_frame(data: bytes) -> ProtocolObject:
    """Decode one exact, complete OpenQSP Core frame into a typed object."""
    operation, payload = _decode_header(data)
    decoder = _DECODERS.get(operation)
    if decoder is None:
        raise ProtocolDecodeError(
            f"payload codec for {operation.name} is deferred to M1.3"
        )
    return decoder(payload)


def encode_frame(obj: ProtocolObject) -> bytes:
    """Encode one supported typed object as an OpenQSP Core frame."""
    entry = _ENCODERS.get(type(obj))
    if entry is None:
        raise ProtocolEncodeError(
            f"payload codec for {type(obj).__name__} is deferred to M1.3"
        )
    operation, encoder = entry
    payload = encoder(obj)
    if len(payload) > 0xFF:
        raise ProtocolEncodeError("payload exceeds the version 0.1 maximum size")
    return bytes((PROTOCOL_VERSION, operation, 0, len(payload))) + payload
