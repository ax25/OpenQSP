"""Shared storage primitives."""
from dataclasses import dataclass
from enum import Enum
MAX_U32 = 0xFFFF_FFFF
MAX_SQLITE_INTEGER = 0x7FFF_FFFF_FFFF_FFFF
class StoreResult(Enum):
    STORED = "stored"
@dataclass(frozen=True)
class StoreOutcome:
    result: StoreResult
    sequence: int
class SequenceExhaustedError(RuntimeError): pass
class StorageIntegrityError(RuntimeError): pass
class InvalidCursorError(ValueError): pass
def require_u32(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_U32:
        raise ValueError(f"{name} must be an unsigned 32-bit integer")
