"""Typed definitions for the OpenQSP Core protocol."""

from .codec import (
    ProtocolObject,
    decode_frame as _decode_frame,
    decode_frame_with_flags,
    encode_frame as _encode_frame,
    normalize_callsign,
    validate_callsign,
)
from .constants import (
    IMPLEMENTED_CAPABILITIES,
    PROTOCOL_VERSION,
    Capability,
    ErrorCode,
    Operation,
)
from .get_message_wire import decode_get_message_frame, encode_get_message_frame
from .models import (
    Bulletin,
    BulletinHeader,
    Capabilities,
    End,
    Error,
    GetBulletin,
    GetCapabilities,
    GetMessage,
    GetNewBulletins,
    GetNewMessages,
    Message,
    SendMessage,
    Stored,
)


def decode_frame(data: bytes):
    if isinstance(data, bytes) and len(data) >= 2 and data[0] == PROTOCOL_VERSION and data[1] == Operation.GET_MESSAGE:
        return decode_get_message_frame(data)
    return _decode_frame(data)


def encode_frame(obj, *, unsolicited: bool = False):
    if isinstance(obj, GetMessage):
        if unsolicited:
            raise ValueError("UNSOLICITED is invalid for GET_MESSAGE")
        return encode_get_message_frame(obj)
    return _encode_frame(obj, unsolicited=unsolicited)


__all__ = [
    "IMPLEMENTED_CAPABILITIES",
    "PROTOCOL_VERSION",
    "Bulletin",
    "BulletinHeader",
    "Capabilities",
    "Capability",
    "End",
    "Error",
    "ErrorCode",
    "GetBulletin",
    "GetCapabilities",
    "GetMessage",
    "GetNewBulletins",
    "GetNewMessages",
    "Message",
    "Operation",
    "ProtocolObject",
    "SendMessage",
    "Stored",
    "decode_frame",
    "decode_frame_with_flags",
    "encode_frame",
    "normalize_callsign",
    "validate_callsign",
]
