"""Bounded reassembly and completed-request replay state."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from openqsp.protocol import decode_frame_with_flags

from .carriage import APRSFragment, CarriageError, decode_frame_text


class TransactionConflict(CarriageError):
    """A transaction ID was reused inconsistently."""


@dataclass
class _Assembly:
    total: int
    first_seen: float
    last_seen: float
    version: int
    parts: dict[int, str | bytes] = field(default_factory=dict)


class Reassembler:
    def __init__(self, *, ttl: float = 120.0, max_entries: int = 128) -> None:
        if ttl <= 0 or max_entries <= 0:
            raise ValueError("reassembly bounds must be positive")
        self.ttl, self.max_entries = ttl, max_entries
        self._entries: OrderedDict[tuple[str, str], _Assembly] = OrderedDict()

    def expire(self, now: float) -> None:
        for key, entry in tuple(self._entries.items()):
            if now - entry.last_seen >= self.ttl:
                del self._entries[key]

    def add(self, peer: str, fragment: APRSFragment, now: float) -> bytes | None:
        self.expire(now)
        key = (peer, fragment.transaction_id)
        entry = self._entries.get(key)
        if entry is None:
            while len(self._entries) >= self.max_entries:
                self._entries.popitem(last=False)
            entry = self._entries[key] = _Assembly(
                fragment.total, now, now, fragment.version
            )
        elif entry.total != fragment.total or entry.version != fragment.version:
            del self._entries[key]
            raise TransactionConflict("inconsistent fragment profile or count")

        part: str | bytes
        if fragment.version == 2:
            if fragment.raw_data is None:
                del self._entries[key]
                raise CarriageError("Q2 fragment is missing raw data")
            part = fragment.raw_data
        else:
            part = fragment.data

        existing = entry.parts.get(fragment.index)
        if existing is not None and existing != part:
            del self._entries[key]
            raise TransactionConflict("conflicting duplicate fragment")
        entry.parts[fragment.index] = part
        entry.last_seen = now
        self._entries.move_to_end(key)
        if len(entry.parts) != entry.total:
            return None
        del self._entries[key]

        if entry.version == 2:
            frame = b"".join(
                bytes(entry.parts[index]) for index in range(entry.total)
            )
            try:
                decode_frame_with_flags(frame)
            except Exception as error:
                raise CarriageError("invalid OpenQSP Q2 frame carriage") from error
            return frame
        return decode_frame_text(
            "".join(str(entry.parts[index]) for index in range(entry.total))
        )

    def __len__(self) -> int:
        return len(self._entries)


@dataclass(frozen=True)
class Replay:
    request: bytes
    responses: tuple[bytes, ...]
    created_at: float


class ReplayCache:
    def __init__(self, *, ttl: float = 600.0, max_entries: int = 256, max_per_peer: int = 16) -> None:
        if min(ttl, max_entries, max_per_peer) <= 0:
            raise ValueError("replay bounds must be positive")
        self.ttl, self.max_entries, self.max_per_peer = ttl, max_entries, max_per_peer
        self._entries: OrderedDict[tuple[str, str], Replay] = OrderedDict()

    def expire(self, now: float) -> None:
        for key, value in tuple(self._entries.items()):
            if now - value.created_at >= self.ttl:
                del self._entries[key]

    def get(self, peer: str, transaction_id: str, now: float) -> Replay | None:
        self.expire(now)
        value = self._entries.get((peer, transaction_id))
        if value is not None:
            self._entries.move_to_end((peer, transaction_id))
        return value

    def put(self, peer: str, transaction_id: str, request: bytes, responses: tuple[bytes, ...], now: float) -> None:
        key = (peer, transaction_id)
        self._entries[key] = Replay(request, responses, now)
        self._entries.move_to_end(key)
        peer_keys = [item for item in self._entries if item[0] == peer]
        while len(peer_keys) > self.max_per_peer:
            del self._entries[peer_keys.pop(0)]
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)
