"""Small primitives shared by immutable object stores."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

MAX_U64 = 0xFFFF_FFFF_FFFF_FFFF
MAX_SQLITE_INTEGER = 0x7FFF_FFFF_FFFF_FFFF


class StoreResult(Enum):
    """Business outcomes from attempting to persist an immutable object."""

    STORED = "stored"
    ALREADY_STORED = "already_stored"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class StoreOutcome:
    """Result of storage, including the stable sequence when applicable."""

    result: StoreResult
    sequence: int | None


class SequenceExhaustedError(RuntimeError):
    """Raised when no further values exist in a u64 sequence space."""


class StorageIntegrityError(RuntimeError):
    """Raised when persisted rows violate the storage schema's invariants."""


def length_prefixed(value: bytes) -> bytes:
    """Encode bytes with an eight-byte length prefix for canonical hashes."""
    return len(value).to_bytes(8, "big") + value


def require_u64(name: str, value: int) -> None:
    """Reject values that cannot be represented as an unsigned 64-bit integer."""
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_U64:
        raise ValueError(f"{name} must be an unsigned 64-bit integer")
