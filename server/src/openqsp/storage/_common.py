"""Validation and exceptions shared by the storage backends."""

MAX_U32 = 0xFFFF_FFFF
MAX_SQLITE_INTEGER = 0x7FFF_FFFF_FFFF_FFFF
MAX_RETRIEVAL_LIMIT = 20


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


def require_nonzero_u32(name: str, value: int) -> None:
    """Reject values that are not non-zero unsigned 32-bit integers."""
    require_u32(name, value)
    if value == 0:
        raise ValueError(f"{name} must be a non-zero unsigned 32-bit integer")


def validate_retrieval_limit(limit: int) -> None:
    """Validate the common storage pagination limit."""
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_RETRIEVAL_LIMIT
    ):
        raise ValueError(
            f"limit must be an integer between 1 and {MAX_RETRIEVAL_LIMIT}"
        )


def validate_clock_value(value: object) -> int:
    """Validate and return a server-assigned SQLite timestamp."""
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= MAX_SQLITE_INTEGER
    ):
        raise ValueError("clock must return a non-negative SQLite integer")
    return value


def validate_stored_u32(value: object, field: str, *, allow_zero: bool = False) -> int:
    """Decode an INTEGER sequence while detecting corrupt database values."""
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not (0 if allow_zero else 1) <= value <= MAX_U32
    ):
        raise StorageIntegrityError(f"{field} is not a valid unsigned 32-bit integer")
    return value
