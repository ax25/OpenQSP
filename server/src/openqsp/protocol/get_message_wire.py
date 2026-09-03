"""Wire codec for the GET_MESSAGE point-retrieval request."""

from __future__ import annotations

from .constants import HEADER_SIZE, MAX_CALLSIGN_LENGTH, MIN_CALLSIGN_LENGTH, PROTOCOL_VERSION, Operation
from .errors import InvalidFieldError, PayloadLengthError, ProtocolDecodeError
from .models import GetMessage


def decode_get_message_frame(data: bytes) -> GetMessage:
    if not isinstance(data, bytes):
        raise ProtocolDecodeError("a Core frame must be bytes")
    if len(data) < HEADER_SIZE:
        raise PayloadLengthError("frame is too short to contain the Core header")
    version, operation, flags, payload_length = data[:HEADER_SIZE]
    if version != PROTOCOL_VERSION or operation != Operation.GET_MESSAGE or flags != 0:
        raise InvalidFieldError("invalid GET_MESSAGE header")
    payload = data[HEADER_SIZE:]
    if payload_length != len(payload):
        raise PayloadLengthError("declared GET_MESSAGE payload length does not match frame")
    if len(payload) < 1 + MIN_CALLSIGN_LENGTH + 4:
        raise PayloadLengthError("GET_MESSAGE payload is truncated")
    peer_length = payload[0]
    if not MIN_CALLSIGN_LENGTH <= peer_length <= MAX_CALLSIGN_LENGTH:
        raise InvalidFieldError("peer has invalid callsign length")
    if len(payload) != 1 + peer_length + 4:
        raise PayloadLengthError("GET_MESSAGE payload contains trailing or missing bytes")
    raw_peer = payload[1 : 1 + peer_length]
    try:
        peer = raw_peer.decode("ascii")
    except UnicodeDecodeError:
        raise InvalidFieldError("peer must be ASCII") from None
    if not peer.isalnum() or peer != peer.upper() or not any(c.isalpha() for c in peer) or not any(c.isdigit() for c in peer):
        raise InvalidFieldError("peer must be a normalized OpenQSP callsign")
    sequence = int.from_bytes(payload[-4:], "big")
    if sequence == 0:
        raise InvalidFieldError("conversation_sequence must be non-zero")
    return GetMessage(peer=peer, conversation_sequence=sequence)


def encode_get_message_frame(value: GetMessage) -> bytes:
    if not isinstance(value.peer, str):
        raise InvalidFieldError("peer must be text")
    peer = value.peer.encode("ascii", errors="strict")
    if not MIN_CALLSIGN_LENGTH <= len(peer) <= MAX_CALLSIGN_LENGTH:
        raise InvalidFieldError("peer has invalid callsign length")
    if not value.peer.isalnum() or value.peer != value.peer.upper() or not any(c.isalpha() for c in value.peer) or not any(c.isdigit() for c in value.peer):
        raise InvalidFieldError("peer must be a normalized OpenQSP callsign")
    sequence = value.conversation_sequence
    if not isinstance(sequence, int) or isinstance(sequence, bool) or not 1 <= sequence <= 0xFFFFFFFF:
        raise InvalidFieldError("conversation_sequence must be a non-zero unsigned 32-bit value")
    payload = bytes((len(peer),)) + peer + sequence.to_bytes(4, "big")
    return bytes((PROTOCOL_VERSION, Operation.GET_MESSAGE, 0, len(payload))) + payload
