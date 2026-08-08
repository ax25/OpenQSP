"""Transport-independent OpenQSP Core version 0.1 frame codec."""

from collections.abc import Callable
from typing import TypeAlias, cast

from .constants import (
    HEADER_SIZE,
    MAX_BULLETIN_BODY_LENGTH,
    MAX_BULLETIN_TITLE_LENGTH,
    MAX_CALLSIGN_LENGTH,
    MAX_ERROR_DETAIL_LENGTH,
    MAX_FRAME_SIZE,
    MAX_MESSAGE_BODY_LENGTH,
    MAX_RETRIEVAL_MAX,
    MIN_BULLETIN_BODY_LENGTH,
    MIN_BULLETIN_TITLE_LENGTH,
    MIN_CALLSIGN_LENGTH,
    MIN_MESSAGE_BODY_LENGTH,
    MIN_RETRIEVAL_MAX,
    PROTOCOL_VERSION,
    AckStatus,
    ErrorCode,
    Operation,
)
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
    SendMessage | GetNewMessages | GetNewBulletins | GetBulletin | Message
    | BulletinHeader | Bulletin | End | Ack | Error
)
PayloadDecoder: TypeAlias = Callable[[bytes], ProtocolObject]
PayloadEncoder: TypeAlias = Callable[[ProtocolObject], bytes]


class _Reader:
    """Minimal bounds-checked payload reader."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.offset = 0

    def take(self, size: int, field: str) -> bytes:
        end = self.offset + size
        if end > len(self.payload):
            raise PayloadLengthError(f"payload is truncated while reading {field}")
        value = self.payload[self.offset:end]
        self.offset = end
        return value

    def u8(self, field: str) -> int:
        return self.take(1, field)[0]

    def u32(self, field: str) -> int:
        return int.from_bytes(self.take(4, field), "big")

    def u64(self, field: str) -> int:
        return int.from_bytes(self.take(8, field), "big")

    def prefixed(self, field: str) -> bytes:
        return self.take(self.u8(f"{field}_length"), field)

    def finish(self) -> None:
        if self.offset != len(self.payload):
            raise PayloadLengthError("payload contains trailing bytes")


def _require_exact(payload: bytes, size: int, operation: str) -> None:
    if len(payload) != size:
        raise PayloadLengthError(f"{operation} payload must be exactly {size} bytes")


def _integer(value: object, bits: int, field: str, *, nonzero: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidFieldError(f"{field} must be an integer")
    maximum = (1 << bits) - 1
    if not 0 <= value <= maximum or (nonzero and value == 0):
        qualifier = "non-zero " if nonzero else ""
        raise InvalidFieldError(f"{field} must be a {qualifier}unsigned {bits}-bit value")
    return value


def _u8(value: object, field: str, *, nonzero: bool = False) -> bytes:
    return _integer(value, 8, field, nonzero=nonzero).to_bytes(1, "big")


def _u32(value: object, field: str, *, nonzero: bool = False) -> bytes:
    return _integer(value, 32, field, nonzero=nonzero).to_bytes(4, "big")


def _u64(value: object, field: str, *, nonzero: bool = False) -> bytes:
    return _integer(value, 64, field, nonzero=nonzero).to_bytes(8, "big")


def _text_bytes(value: object, field: str, minimum: int, maximum: int) -> bytes:
    if not isinstance(value, str):
        raise InvalidFieldError(f"{field} must be text")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidFieldError(f"{field} must be valid UTF-8") from None
    if b"\x00" in encoded:
        raise InvalidFieldError(f"{field} must not contain NUL")
    if not minimum <= len(encoded) <= maximum:
        raise InvalidFieldError(
            f"{field} must contain between {minimum} and {maximum} UTF-8 bytes"
        )
    return encoded


def _decode_text(data: bytes, field: str, minimum: int, maximum: int) -> str:
    if not minimum <= len(data) <= maximum:
        raise InvalidFieldError(
            f"{field} must contain between {minimum} and {maximum} UTF-8 bytes"
        )
    if b"\x00" in data:
        raise InvalidFieldError(f"{field} must not contain NUL")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise InvalidFieldError(f"{field} must be valid UTF-8") from None


def _callsign_bytes(value: object, field: str) -> bytes:
    encoded = _text_bytes(value, field, MIN_CALLSIGN_LENGTH, MAX_CALLSIGN_LENGTH)
    if any(byte not in range(48, 58) and byte not in range(65, 91) for byte in encoded):
        raise InvalidFieldError(f"{field} must contain only uppercase ASCII A-Z and 0-9")
    if not any(65 <= byte <= 90 for byte in encoded) or not any(48 <= byte <= 57 for byte in encoded):
        raise InvalidFieldError(f"{field} must contain at least one letter and one number")
    return encoded


def validate_callsign(value: object, field: str = "callsign") -> str:
    """Validate and return an already-normalized OpenQSP callsign.

    This deliberately does not normalize input.  It exposes the codec's
    canonical callsign rules for trusted values that originate outside a
    frame, such as an authenticated server context.
    """

    _callsign_bytes(value, field)
    return cast(str, value)


def _decode_callsign(data: bytes, field: str) -> str:
    try:
        value = data.decode("ascii")
    except UnicodeDecodeError:
        raise InvalidFieldError(f"{field} must be ASCII") from None
    _callsign_bytes(value, field)
    return value


def _prefix(data: bytes) -> bytes:
    return _u8(len(data), "length") + data


def _decode_send_message(payload: bytes) -> SendMessage:
    reader = _Reader(payload)
    message_id = reader.u64("message_id")
    created_at = reader.u32("created_at")
    recipient = _decode_callsign(reader.prefixed("recipient"), "recipient")
    body = _decode_text(reader.prefixed("body"), "body", MIN_MESSAGE_BODY_LENGTH, MAX_MESSAGE_BODY_LENGTH)
    reader.finish()
    _integer(message_id, 64, "message_id", nonzero=True)
    _integer(created_at, 32, "created_at", nonzero=True)
    return SendMessage(message_id, created_at, recipient, body)


def _encode_send_message(obj: ProtocolObject) -> bytes:
    value = cast(SendMessage, obj)
    recipient = _callsign_bytes(value.recipient, "recipient")
    body = _text_bytes(value.body, "body", MIN_MESSAGE_BODY_LENGTH, MAX_MESSAGE_BODY_LENGTH)
    return _u64(value.message_id, "message_id", nonzero=True) + _u32(value.created_at, "created_at", nonzero=True) + _prefix(recipient) + _prefix(body)


def _decode_retrieval(payload: bytes, model: type[GetNewMessages] | type[GetNewBulletins], name: str) -> ProtocolObject:
    _require_exact(payload, 9, name)
    since, maximum = int.from_bytes(payload[:8], "big"), payload[8]
    if not MIN_RETRIEVAL_MAX <= maximum <= MAX_RETRIEVAL_MAX:
        raise InvalidFieldError(f"max must be between {MIN_RETRIEVAL_MAX} and {MAX_RETRIEVAL_MAX}")
    return model(since=since, max=maximum)


def _encode_retrieval(obj: GetNewMessages | GetNewBulletins) -> bytes:
    maximum = _integer(obj.max, 8, "max")
    if not MIN_RETRIEVAL_MAX <= maximum <= MAX_RETRIEVAL_MAX:
        raise InvalidFieldError(f"max must be between {MIN_RETRIEVAL_MAX} and {MAX_RETRIEVAL_MAX}")
    return _u64(obj.since, "since") + bytes((maximum,))


def _decode_get_new_messages(payload: bytes) -> GetNewMessages:
    return cast(GetNewMessages, _decode_retrieval(payload, GetNewMessages, "GET_NEW_MESSAGES"))


def _decode_get_new_bulletins(payload: bytes) -> GetNewBulletins:
    return cast(GetNewBulletins, _decode_retrieval(payload, GetNewBulletins, "GET_NEW_BULLETINS"))


def _encode_get_new_messages(obj: ProtocolObject) -> bytes:
    return _encode_retrieval(cast(GetNewMessages, obj))


def _encode_get_new_bulletins(obj: ProtocolObject) -> bytes:
    return _encode_retrieval(cast(GetNewBulletins, obj))


def _decode_get_bulletin(payload: bytes) -> GetBulletin:
    _require_exact(payload, 8, "GET_BULLETIN")
    bulletin_id = int.from_bytes(payload, "big")
    _integer(bulletin_id, 64, "bulletin_id", nonzero=True)
    return GetBulletin(bulletin_id)


def _encode_get_bulletin(obj: ProtocolObject) -> bytes:
    return _u64(cast(GetBulletin, obj).bulletin_id, "bulletin_id", nonzero=True)


def _decode_message(payload: bytes) -> Message:
    reader = _Reader(payload)
    sequence, message_id, created_at = reader.u64("sequence"), reader.u64("message_id"), reader.u32("created_at")
    author = _decode_callsign(reader.prefixed("author"), "author")
    recipient = _decode_callsign(reader.prefixed("recipient"), "recipient")
    body = _decode_text(reader.prefixed("body"), "body", MIN_MESSAGE_BODY_LENGTH, MAX_MESSAGE_BODY_LENGTH)
    reader.finish()
    _integer(sequence, 64, "sequence", nonzero=True)
    _integer(message_id, 64, "message_id", nonzero=True)
    _integer(created_at, 32, "created_at", nonzero=True)
    return Message(sequence, message_id, created_at, author, recipient, body)


def _encode_message(obj: ProtocolObject) -> bytes:
    value = cast(Message, obj)
    author, recipient = _callsign_bytes(value.author, "author"), _callsign_bytes(value.recipient, "recipient")
    body = _text_bytes(value.body, "body", MIN_MESSAGE_BODY_LENGTH, MAX_MESSAGE_BODY_LENGTH)
    return _u64(value.sequence, "sequence", nonzero=True) + _u64(value.message_id, "message_id", nonzero=True) + _u32(value.created_at, "created_at", nonzero=True) + _prefix(author) + _prefix(recipient) + _prefix(body)


def _decode_bulletin_header(payload: bytes) -> BulletinHeader:
    reader = _Reader(payload)
    sequence, bulletin_id, created_at = reader.u64("sequence"), reader.u64("bulletin_id"), reader.u32("created_at")
    author = _decode_callsign(reader.prefixed("author"), "author")
    title = _decode_text(reader.prefixed("title"), "title", MIN_BULLETIN_TITLE_LENGTH, MAX_BULLETIN_TITLE_LENGTH)
    reader.finish()
    _integer(sequence, 64, "sequence", nonzero=True)
    _integer(bulletin_id, 64, "bulletin_id", nonzero=True)
    _integer(created_at, 32, "created_at", nonzero=True)
    return BulletinHeader(sequence, bulletin_id, created_at, author, title)


def _encode_bulletin_header(obj: ProtocolObject) -> bytes:
    value = cast(BulletinHeader, obj)
    author = _callsign_bytes(value.author, "author")
    title = _text_bytes(value.title, "title", MIN_BULLETIN_TITLE_LENGTH, MAX_BULLETIN_TITLE_LENGTH)
    return _u64(value.sequence, "sequence", nonzero=True) + _u64(value.bulletin_id, "bulletin_id", nonzero=True) + _u32(value.created_at, "created_at", nonzero=True) + _prefix(author) + _prefix(title)


def _decode_bulletin(payload: bytes) -> Bulletin:
    reader = _Reader(payload)
    bulletin_id, created_at = reader.u64("bulletin_id"), reader.u32("created_at")
    author = _decode_callsign(reader.prefixed("author"), "author")
    title = _decode_text(reader.prefixed("title"), "title", MIN_BULLETIN_TITLE_LENGTH, MAX_BULLETIN_TITLE_LENGTH)
    body = _decode_text(reader.prefixed("body"), "body", MIN_BULLETIN_BODY_LENGTH, MAX_BULLETIN_BODY_LENGTH)
    reader.finish()
    _integer(bulletin_id, 64, "bulletin_id", nonzero=True)
    _integer(created_at, 32, "created_at", nonzero=True)
    return Bulletin(bulletin_id, created_at, author, title, body)


def _encode_bulletin(obj: ProtocolObject) -> bytes:
    value = cast(Bulletin, obj)
    author = _callsign_bytes(value.author, "author")
    title = _text_bytes(value.title, "title", MIN_BULLETIN_TITLE_LENGTH, MAX_BULLETIN_TITLE_LENGTH)
    body = _text_bytes(value.body, "body", MIN_BULLETIN_BODY_LENGTH, MAX_BULLETIN_BODY_LENGTH)
    return _u64(value.bulletin_id, "bulletin_id", nonzero=True) + _u32(value.created_at, "created_at", nonzero=True) + _prefix(author) + _prefix(title) + _prefix(body)


def _decode_end(payload: bytes) -> End:
    _require_exact(payload, 11, "END")
    try:
        request_operation = Operation(payload[0])
    except ValueError:
        raise InvalidFieldError("END request_operation must be a retrieval operation") from None
    if request_operation not in (Operation.GET_NEW_MESSAGES, Operation.GET_NEW_BULLETINS):
        raise InvalidFieldError("END request_operation must be a retrieval operation")
    if payload[10] not in (0, 1):
        raise InvalidFieldError("has_more must be 0x00 or 0x01")
    return End(request_operation, payload[1], int.from_bytes(payload[2:10], "big"), bool(payload[10]))


def _encode_end(obj: ProtocolObject) -> bytes:
    value = cast(End, obj)
    if not isinstance(value.request_operation, Operation) or value.request_operation not in (Operation.GET_NEW_MESSAGES, Operation.GET_NEW_BULLETINS):
        raise InvalidFieldError("END request_operation must be a retrieval operation")
    if not isinstance(value.has_more, bool):
        raise InvalidFieldError("has_more must be a bool")
    return bytes((value.request_operation,)) + _u8(value.returned_count, "returned_count") + _u64(value.next_since, "next_since") + bytes((value.has_more,))


def _decode_ack(payload: bytes) -> Ack:
    _require_exact(payload, 9, "ACK")
    object_id = int.from_bytes(payload[:8], "big")
    _integer(object_id, 64, "object_id", nonzero=True)
    try:
        status = AckStatus(payload[8])
    except ValueError:
        raise InvalidFieldError(f"unknown ACK status: 0x{payload[8]:02x}") from None
    return Ack(object_id, status)


def _encode_ack(obj: ProtocolObject) -> bytes:
    value = cast(Ack, obj)
    if not isinstance(value.status, AckStatus):
        raise InvalidFieldError("status must be a known AckStatus")
    return _u64(value.object_id, "object_id", nonzero=True) + bytes((value.status,))


def _decode_error(payload: bytes) -> Error:
    reader = _Reader(payload)
    operation_code, error_code = reader.u8("request_operation"), reader.u8("error_code")
    detail = _decode_text(reader.prefixed("detail"), "detail", 0, MAX_ERROR_DETAIL_LENGTH)
    reader.finish()
    if operation_code == 0:
        request_operation: Operation | int = 0
    else:
        try:
            request_operation = Operation(operation_code)
        except ValueError:
            raise InvalidFieldError(f"unknown request_operation: 0x{operation_code:02x}") from None
    try:
        code = ErrorCode(error_code)
    except ValueError:
        raise InvalidFieldError(f"unknown ERROR code: 0x{error_code:02x}") from None
    return Error(request_operation, code, detail)


def _encode_error(obj: ProtocolObject) -> bytes:
    value = cast(Error, obj)
    if value.request_operation == 0 and not isinstance(value.request_operation, bool):
        operation_code = 0
    elif isinstance(value.request_operation, Operation):
        operation_code = value.request_operation
    else:
        raise InvalidFieldError("request_operation must be zero or a known Operation")
    if not isinstance(value.error_code, ErrorCode):
        raise InvalidFieldError("error_code must be a known ErrorCode")
    detail = _text_bytes(value.detail, "detail", 0, MAX_ERROR_DETAIL_LENGTH)
    return bytes((operation_code, value.error_code)) + _prefix(detail)


_DECODERS: dict[Operation, PayloadDecoder] = {
    Operation.SEND_MESSAGE: _decode_send_message,
    Operation.GET_NEW_MESSAGES: _decode_get_new_messages,
    Operation.GET_NEW_BULLETINS: _decode_get_new_bulletins,
    Operation.GET_BULLETIN: _decode_get_bulletin,
    Operation.MESSAGE: _decode_message,
    Operation.BULLETIN_HEADER: _decode_bulletin_header,
    Operation.BULLETIN: _decode_bulletin,
    Operation.END: _decode_end,
    Operation.ACK: _decode_ack,
    Operation.ERROR: _decode_error,
}
_ENCODERS: dict[type[object], tuple[Operation, PayloadEncoder]] = {
    SendMessage: (Operation.SEND_MESSAGE, _encode_send_message),
    GetNewMessages: (Operation.GET_NEW_MESSAGES, _encode_get_new_messages),
    GetNewBulletins: (Operation.GET_NEW_BULLETINS, _encode_get_new_bulletins),
    GetBulletin: (Operation.GET_BULLETIN, _encode_get_bulletin),
    Message: (Operation.MESSAGE, _encode_message),
    BulletinHeader: (Operation.BULLETIN_HEADER, _encode_bulletin_header),
    Bulletin: (Operation.BULLETIN, _encode_bulletin),
    End: (Operation.END, _encode_end),
    Ack: (Operation.ACK, _encode_ack),
    Error: (Operation.ERROR, _encode_error),
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
        raise UnknownOperationError(f"unknown version 0.1 operation: 0x{operation_code:02x}") from None
    if flags != 0:
        raise InvalidFieldError("version 0.1 flags must be 0x00")
    actual = len(data) - HEADER_SIZE
    if actual != payload_length:
        raise PayloadLengthError(f"declared payload length does not match the complete frame ({payload_length} declared, {actual} present)")
    return operation, data[HEADER_SIZE:]


def decode_frame(data: bytes) -> ProtocolObject:
    """Decode one exact, complete OpenQSP Core frame into a typed object."""
    operation, payload = _decode_header(data)
    return _DECODERS[operation](payload)


def encode_frame(obj: ProtocolObject) -> bytes:
    """Encode one typed object as an OpenQSP Core frame."""
    entry = _ENCODERS.get(type(obj))
    if entry is None:
        raise ProtocolEncodeError(f"unsupported protocol object: {type(obj).__name__}")
    operation, encoder = entry
    payload = encoder(obj)
    if len(payload) > 0xFF:
        raise ProtocolEncodeError("payload exceeds the version 0.1 maximum size")
    return bytes((PROTOCOL_VERSION, operation, 0, len(payload))) + payload
