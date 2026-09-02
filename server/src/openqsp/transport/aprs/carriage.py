"""Canonical OpenQSP frame carriage over APRS messages.

Q1 is retained for backwards-compatible parsing.  Q2 is the compact profile:
``Q2`` followed by basE91 of a two-byte fragment header plus raw Core bytes.
The Q2 header is ``transaction:u8`` + ``index:u4,total_minus_one:u4``.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass

from openqsp.protocol import decode_frame_with_flags
from openqsp.protocol.constants import MAX_FRAME_SIZE

DATA_CHUNK_SIZE = 48
V2_DATA_CHUNK_SIZE = 50
MAX_FRAGMENTS = 16
MAX_APRS_BODY = 67
_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_TEXT_RE = re.compile(r"[A-Za-z0-9_-]+")
_FRAGMENT_RE = re.compile(
    r"Q1:([0-9A-Z]{3}):([0-9A-Z]{2})/([0-9A-Z]{2}):([A-Za-z0-9_-]{1,48})"
)
_BASE91_ALPHABET = "".join(
    chr(value) for value in range(33, 127) if chr(value) not in "{|~"
)
_BASE91_DECODE = {character: index for index, character in enumerate(_BASE91_ALPHABET)}


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


def base91_encode(data: bytes) -> str:
    """Encode bytes with the APRS-safe 91-character OpenQSP alphabet."""
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    value = bits = 0
    output: list[str] = []
    for byte in data:
        value |= byte << bits
        bits += 8
        if bits > 13:
            encoded = value & 8191
            if encoded > 88:
                value >>= 13
                bits -= 13
            else:
                encoded = value & 16383
                value >>= 14
                bits -= 14
            output.append(_BASE91_ALPHABET[encoded % 91])
            output.append(_BASE91_ALPHABET[encoded // 91])
    if bits:
        output.append(_BASE91_ALPHABET[value % 91])
        if bits > 7 or value > 90:
            output.append(_BASE91_ALPHABET[value // 91])
    return "".join(output)


def base91_decode(text: str) -> bytes:
    """Decode the APRS-safe OpenQSP basE91 alphabet."""
    if not isinstance(text, str) or not text:
        raise CarriageError("invalid Base91 text")
    value = -1
    accumulator = bits = 0
    output = bytearray()
    try:
        for character in text:
            decoded = _BASE91_DECODE[character]
            if value < 0:
                value = decoded
                continue
            value += decoded * 91
            accumulator |= value << bits
            bits += 13 if (value & 8191) > 88 else 14
            while bits >= 8:
                output.append(accumulator & 0xFF)
                accumulator >>= 8
                bits -= 8
            value = -1
    except KeyError as error:
        raise CarriageError("invalid Base91 character") from error
    if value >= 0:
        accumulator |= value << bits
        bits += 7
        while bits >= 8:
            output.append(accumulator & 0xFF)
            accumulator >>= 8
            bits -= 8
    return bytes(output)


def encode_frame_text(frame: bytes) -> str:
    """Legacy Q1 Base64url frame encoding."""
    if not isinstance(frame, bytes):
        raise TypeError("frame must be bytes")
    if not frame or len(frame) > MAX_FRAME_SIZE:
        raise CarriageError("frame size is outside the OpenQSP bounds")
    decode_frame_with_flags(frame)
    return base64.urlsafe_b64encode(frame).rstrip(b"=").decode("ascii")


def decode_frame_text(text: str) -> bytes:
    """Legacy Q1 Base64url frame decoding."""
    if not isinstance(text, str) or not text or _TEXT_RE.fullmatch(text) is None:
        raise CarriageError("invalid unpadded Base64url text")
    if len(text) % 4 == 1:
        raise CarriageError("impossible unpadded Base64url length")
    try:
        frame = base64.b64decode(
            text + "=" * (-len(text) % 4), altchars=b"-_", validate=True
        )
        decode_frame_with_flags(frame)
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
    version: int = 1
    raw_data: bytes | None = None

    @property
    def body(self) -> str:
        if self.version == 2:
            transaction = parse_base36(self.transaction_id, 3)
            if transaction > 0xFF:
                raise CarriageError("Q2 transaction ID must fit in one byte")
            if not 0 <= self.index < self.total <= MAX_FRAGMENTS:
                raise CarriageError("fragment index or count is outside profile bounds")
            raw = self.raw_data
            if raw is None:
                raise CarriageError("Q2 fragment is missing raw data")
            descriptor = (self.index << 4) | (self.total - 1)
            text = "Q2" + base91_encode(bytes((transaction, descriptor)) + raw)
            if len(text) > MAX_APRS_BODY:
                raise CarriageError("Q2 fragment exceeds APRS message body limit")
            return text
        text = f"Q1:{self.transaction_id}:{base36(self.index, 2)}/{base36(self.total, 2)}:{self.data}"
        return text if self.message_id is None else f"{text}{{{self.message_id}"


def fragment_frame(frame: bytes, transaction_id: str) -> tuple[APRSFragment, ...]:
    """Legacy Q1 fragmentation."""
    parse_base36(transaction_id, 3)
    encoded = encode_frame_text(frame)
    chunks = tuple(encoded[i : i + DATA_CHUNK_SIZE] for i in range(0, len(encoded), DATA_CHUNK_SIZE))
    if not chunks or len(chunks) > MAX_FRAGMENTS:
        raise CarriageError("frame exceeds the 16-fragment profile limit")
    return tuple(APRSFragment(transaction_id, i, len(chunks), chunk) for i, chunk in enumerate(chunks))


def fragment_frame_v2(frame: bytes, transaction_id: str) -> tuple[APRSFragment, ...]:
    """Fragment a validated Core frame directly into compact Q2 chunks."""
    transaction = parse_base36(transaction_id, 3)
    if transaction > 0xFF:
        raise CarriageError("Q2 transaction ID must fit in one byte")
    if not isinstance(frame, bytes) or not frame or len(frame) > MAX_FRAME_SIZE:
        raise CarriageError("frame size is outside the OpenQSP bounds")
    decode_frame_with_flags(frame)
    chunks = tuple(
        frame[i : i + V2_DATA_CHUNK_SIZE]
        for i in range(0, len(frame), V2_DATA_CHUNK_SIZE)
    )
    if not chunks or len(chunks) > MAX_FRAGMENTS:
        raise CarriageError("frame exceeds the 16-fragment profile limit")
    fragments = tuple(
        APRSFragment(
            transaction_id,
            index,
            len(chunks),
            base91_encode(chunk),
            version=2,
            raw_data=chunk,
        )
        for index, chunk in enumerate(chunks)
    )
    # Validate the configured chunk size against the actual APRS body ceiling.
    for fragment in fragments:
        fragment.body
    return fragments


def _parse_q2(body: str) -> APRSFragment:
    if "{" in body:
        raise CarriageError("Q2 fragments must not use APRS message IDs")
    encoded = body[2:]
    decoded = base91_decode(encoded)
    if len(decoded) < 3:
        raise CarriageError("Q2 fragment is truncated")
    transaction, descriptor = decoded[0], decoded[1]
    index, total = descriptor >> 4, (descriptor & 0x0F) + 1
    if index >= total:
        raise CarriageError("fragment index or count is outside profile bounds")
    raw = decoded[2:]
    if not raw or len(raw) > V2_DATA_CHUNK_SIZE:
        raise CarriageError("Q2 fragment payload is outside profile bounds")
    return APRSFragment(
        base36(transaction, 3),
        index,
        total,
        base91_encode(raw),
        version=2,
        raw_data=raw,
    )


def parse_fragment(body: str) -> APRSFragment:
    if not isinstance(body, str):
        raise TypeError("body must be text")
    if body.startswith("Q2"):
        return _parse_q2(body)
    message_id = None
    carriage = body
    if "{" in body:
        carriage, message_id = body.rsplit("{", 1)
        if not message_id or len(message_id) > 5 or any(c not in _B36 for c in message_id):
            raise CarriageError("invalid APRS message ID")
    match = _FRAGMENT_RE.fullmatch(carriage)
    if match is None:
        raise CarriageError("malformed OpenQSP fragment")
    transaction_id, raw_index, raw_total, data = match.groups()
    index, total = parse_base36(raw_index, 2), parse_base36(raw_total, 2)
    if not 1 <= total <= MAX_FRAGMENTS or index >= total:
        raise CarriageError("fragment index or count is outside profile bounds")
    return APRSFragment(transaction_id, index, total, data, message_id)
