"""Typed definitions for the OpenQSP Core protocol."""

from .codec import (
    ProtocolObject,
    decode_frame as _decode_frame,
    decode_frame_with_flags as _decode_frame_with_flags,
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


def _is_get_message_frame(data: object) -> bool:
    return (
        isinstance(data, bytes)
        and len(data) >= 2
        and data[0] == PROTOCOL_VERSION
        and data[1] == Operation.GET_MESSAGE
    )


def decode_frame(data: bytes):
    if _is_get_message_frame(data):
        return decode_get_message_frame(data)
    return _decode_frame(data)


def decode_frame_with_flags(data: bytes):
    """Decode a node-originated frame while preserving Core flags.

    GET_MESSAGE is a client request and therefore can never be UNSOLICITED, but
    APRS Q1/Q2 carriage validates every complete Core frame through this entry
    point before dispatch.  Route operation 0x06 through the selective lookup
    codec here as well so a valid GET_MESSAGE request is not rejected by the
    generic codec before it reaches ServerCore.
    """
    if _is_get_message_frame(data):
        return decode_get_message_frame(data), 0
    return _decode_frame_with_flags(data)


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
