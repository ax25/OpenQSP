"""Small primitives shared by persistent object stores."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

MAX_U32 = 0xFFFF_FFFF
MAX_SQLITE_INTEGER = 0x7FFF_FFFF_FFFF_FFFF


class StoreResult(Enum):
    """Business outcome from persisting a new application object."""

    STORED = "stored"


@dataclass(frozen=True)
class StoreOutcome:
    """Successful storage result, including the allocated sequence."""

    result: StoreResult
    sequence: int


class SequenceExhaustedError(RuntimeError):
    """Raised when no further values exist in a u32 sequence space."""


class StorageIntegrityError(RuntimeError):
    """Raised when persisted rows violate storage invariants."""


class InvalidCursorError(ValueError):
    """Raised when a retrieval cursor is ahead of its scoped stream."""


def require_u32(name: str, value: int) -> None:
    """Reject values that cannot be represented as unsigned 32-bit integers."""
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= MAX_U32
    ):
        raise ValueError(f"{name} must be an unsigned 32-bit integer")
