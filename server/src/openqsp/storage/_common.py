"""Validation and exceptions shared by the storage backends."""

MAX_U32 = 0xFFFF_FFFF
MAX_SQLITE_INTEGER = 0x7FFF_FFFF_FFFF_FFFF


class SequenceExhaustedError(RuntimeError):
    """Raised when no further values exist in a u32 sequence space."""


class StorageIntegrityError(RuntimeError):
    """Raised when persisted rows violate storage invariants."""


class InvalidCursorError(ValueError):
    """Raised when a cursor is ahead of its scoped sequence."""


def require_u32(name: str, value: int) -> None:
    """Reject values that are not unsigned 32-bit integers."""
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= MAX_U32
    ):
        raise ValueError(f"{name} must be an unsigned 32-bit integer")
