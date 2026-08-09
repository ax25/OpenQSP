"""Canonical text carriage for complete OpenQSP frames over APRS messages."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass

from openqsp.protocol import decode_frame
from openqsp.protocol.constants import MAX_FRAME_SIZE

DATA_CHUNK_SIZE = 48
MAX_FRAGMENTS = 16
_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_TEXT_RE = re.compile(r"[A-Za-z0-9_-]+")
_FRAGMENT_RE = re.compile(
    r"Q1:([0-9A-Z]{3}):([0-9A-Z]{2})/([0-9A-Z]{2}):([A-Za-z0-9_-]{1,48})"
)


class CarriageError(ValueError):
    """Malformed or untransportable APRS carriage data."""


def base36(value: int, width: int) -> str:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < 36**width:
        raise CarriageError(f"value does not fit in {width} base36 characters")
    result = ""
    for _ in range(width):
        value, digit = divmod(value, 36)
        result = _B36[digit] + result
    return result


def parse_base36(value: str, width: int) -> int:
    if len(value) != width or any(character not in _B36 for character in value):
        raise CarriageError(f"expected {width} uppercase base36 characters")
    return int(value, 36)


def encode_frame_text(frame: bytes) -> str:
    if not isinstance(frame, bytes):
        raise TypeError("frame must be bytes")
    if not frame or len(frame) > MAX_FRAME_SIZE:
        raise CarriageError("frame size is outside the OpenQSP bounds")
    decode_frame(frame)
    return base64.urlsafe_b64encode(frame).rstrip(b"=").decode("ascii")


def decode_frame_text(text: str) -> bytes:
    if not isinstance(text, str) or not text or _TEXT_RE.fullmatch(text) is None:
        raise CarriageError("invalid unpadded Base64url text")
    if len(text) % 4 == 1:
        raise CarriageError("impossible unpadded Base64url length")
    try:
        frame = base64.b64decode(
            text + "=" * (-len(text) % 4), altchars=b"-_", validate=True
        )
        decode_frame(frame)
    except Exception as error:
        raise CarriageError("invalid OpenQSP frame carriage") from error
    return frame


@dataclass(frozen=True)
class APRSFragment:
    transaction_id: str
    index: int
    total: int
    data: str
    message_id: str | None = None

    @property
    def body(self) -> str:
        text = f"Q1:{self.transaction_id}:{base36(self.index, 2)}/{base36(self.total, 2)}:{self.data}"
        return text if self.message_id is None else f"{text}{{{self.message_id}"


def fragment_frame(frame: bytes, transaction_id: str) -> tuple[APRSFragment, ...]:
    parse_base36(transaction_id, 3)
    encoded = encode_frame_text(frame)
    chunks = tuple(encoded[i : i + DATA_CHUNK_SIZE] for i in range(0, len(encoded), DATA_CHUNK_SIZE))
    if not chunks or len(chunks) > MAX_FRAGMENTS:
        raise CarriageError("frame exceeds the 16-fragment profile limit")
    return tuple(APRSFragment(transaction_id, i, len(chunks), chunk) for i, chunk in enumerate(chunks))


def parse_fragment(body: str) -> APRSFragment:
    if not isinstance(body, str):
        raise TypeError("body must be text")
    message_id = None
    carriage = body
    if "{" in body:
        carriage, message_id = body.rsplit("{", 1)
        if not message_id or len(message_id) > 5 or any(c not in _B36 for c in message_id):
            raise CarriageError("invalid APRS message ID")
    match = _FRAGMENT_RE.fullmatch(carriage)
    if match is None:
        raise CarriageError("malformed Q1 fragment")
    transaction_id, raw_index, raw_total, data = match.groups()
    index, total = parse_base36(raw_index, 2), parse_base36(raw_total, 2)
    if not 1 <= total <= MAX_FRAGMENTS or index >= total:
        raise CarriageError("fragment index or count is outside profile bounds")
    return APRSFragment(transaction_id, index, total, data, message_id)
