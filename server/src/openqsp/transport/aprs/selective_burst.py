"""Transaction-level APRS burst delivery with selective repair.

Q2 carries raw OpenQSP Core bytes using the compact APRS-safe Base91 carriage.
Positive receipt is transaction-level ``A2``; selective repair is ``N2`` with
a 16-bit missing-fragment bitmap. Successful SEND_MESSAGE completion is the
compact ``S2`` durable result, correlated to the inbound transaction. Legacy
Q1A/Q1N controls remain parseable while peers migrate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from openqsp.protocol import SendMessage, Stored, decode_frame, normalize_callsign

from .adapter import OutboundPacket
from .carriage import (
    APRSFragment,
    CarriageError,
    base36,
    base91_decode,
    base91_encode,
    fragment_frame_v2,
    parse_base36,
    parse_fragment,
)
from .commit_adapter import APRSAdapter as _CommitAPRSAdapter

_ACK_RE = re.compile(r"Q1A:([0-9A-Z]{3})")
_NACK_RE = re.compile(r"Q1N:([0-9A-Z]{3}):([0-9A-F]{4})")


def _transaction_byte(transaction_id: str) -> int:
    value = parse_base36(transaction_id, 3)
    if value > 0xFF:
        raise CarriageError("Q2 transaction ID must fit in one byte")
    return value


def encode_burst_ack(transaction_id: str) -> str:
    return "A2" + base91_encode(bytes((_transaction_byte(transaction_id),)))


def encode_stored(transaction_id: str) -> str:
    """Encode durable SEND_MESSAGE completion for an inbound Q2 transaction."""
    return "S2" + base91_encode(bytes((_transaction_byte(transaction_id),)))


def parse_stored(body: str) -> str | None:
    if not body.startswith("S2"):
        return None
    try:
        payload = base91_decode(body[2:])
    except CarriageError:
        return None
    if len(payload) != 1:
        return None
    return base36(payload[0], 3)


def encode_missing(transaction_id: str, missing: set[int] | frozenset[int]) -> str:
    mask = 0
    for index in missing:
        if not 0 <= index < 16:
            raise CarriageError("missing fragment index is outside profile bounds")
        mask |= 1 << index
    if mask == 0:
        raise CarriageError("missing-fragment mask must not be empty")
    payload = bytes((_transaction_byte(transaction_id),)) + mask.to_bytes(2, "big")
    return "N2" + base91_encode(payload)


def parse_burst_control(body: str) -> tuple[str, str, frozenset[int]] | None:
    if body.startswith("A2"):
        try:
            payload = base91_decode(body[2:])
        except CarriageError:
            return None
        if len(payload) != 1:
            return None
        return ("ack", base36(payload[0], 3), frozenset())
    if body.startswith("N2"):
        try:
            payload = base91_decode(body[2:])
        except CarriageError:
            return None
        if len(payload) != 3:
            return None
        mask = int.from_bytes(payload[1:], "big")
        if mask == 0:
            return None
        return (
            "missing",
            base36(payload[0], 3),
            frozenset(index for index in range(16) if mask & (1 << index)),
        )

    ack = _ACK_RE.fullmatch(body)
    if ack is not None:
        return ("ack", ack.group(1), frozenset())
    nack = _NACK_RE.fullmatch(body)
    if nack is None:
        return None
    mask = int(nack.group(2), 16)
    if mask == 0:
        return None
    return (
        "missing",
        nack.group(1),
        frozenset(index for index in range(16) if mask & (1 << index)),
    )


@dataclass
class _BurstTx:
    peer: str
    transaction_id: str
    fragments: tuple[APRSFragment, ...]
    packets: tuple[OutboundPacket, ...]
    priority: int
    order: int
    delivery: tuple[str, int] | None
    response_batch: tuple[str, str] | None
    response_supersedable: bool
    attempts: int = 0
    deadline: float = 0.0
    requested: frozenset[int] | None = None
    repair_active: bool = False
    repair_indices: frozenset[int] | None = None


@dataclass
class _RxProgress:
    total: int
    received: set[int] = field(default_factory=set)
    deadline: float = 0.0
    saw_final: bool = False

    @property
    def missing(self) -> set[int]:
        return set(range(self.total)) - self.received


class APRSAdapter(_CommitAPRSAdapter):
    """APRS adapter using compact Q2 transaction ACK/NACK reliability."""

    def __init__(
        self,
        *args,
        repair_grace: float = 5.0,
        final_fragment_grace: float = 2.0,
        **kwargs,
    ) -> None:
        if repair_grace <= 0:
            raise ValueError("repair_grace must be positive")
        if final_fragment_grace <= 0:
            raise ValueError("final_fragment_grace must be positive")
        super().__init__(*args, **kwargs)
        self.repair_grace = repair_grace
        self.final_fragment_grace = final_fragment_grace
        self._burst_queue: list[_BurstTx] = []
        self._burst_active: dict[str, _BurstTx] = {}
        self._rx_progress: dict[tuple[str, str], _RxProgress] = {}
        self._burst_order = 0

    def _allocate(self, peer: str, *, transaction: bool) -> str:
        if not transaction:
            return super()._allocate(peer, transaction=False)
        active = self._active_transactions(peer)
        for _ in range(256):
            value = self._next_transaction[peer] % 256
            self._next_transaction[peer] = value + 1
            candidate = base36(value, 3)
            if candidate not in active:
                return candidate
        raise OverflowError("peer Q2 transaction ID space exhausted")

    def _active_transactions(self, peer: str) -> set[str]:
        active = super()._active_transactions(peer)
        active.update(
            tx.transaction_id for tx in self._burst_queue if tx.peer == peer
        )
        current = self._burst_active.get(peer)
        if current is not None:
            active.add(current.transaction_id)
        return active

    @property
    def queued_count(self) -> int:
        return sum(len(tx.fragments) for tx in self._burst_queue)

    @property
    def pending_count(self) -> int:
        return sum(len(tx.fragments) for tx in self._burst_active.values())

    def _supersede_active_response_for_proactive(self, peer: str) -> None:
        active = self._burst_active.get(peer)
        if (
            active is None
            or active.response_batch is None
            or not active.response_supersedable
        ):
            return
        stale_batch = active.response_batch
        del self._burst_active[peer]
        self._burst_queue = [
            tx
            for tx in self._burst_queue
            if not (tx.peer == peer and tx.response_batch == stale_batch)
        ]

    def queue_frame(
        self,
        peer: str,
        frame: bytes,
        *,
        proactive: bool = False,
        delivery: tuple[str, int] | None = None,
        response_batch: tuple[str, str] | None = None,
        response_supersedable: bool = True,
    ) -> str:
        self.validate_peer(peer)
        if proactive:
            self._supersede_active_response_for_proactive(peer)
        transaction_id = self._allocate(peer, transaction=True)
        fragments = fragment_frame_v2(frame, transaction_id)
        current_load = self.queued_count + self.pending_count
        if current_load + len(fragments) > self.config.queue_capacity:
            raise OverflowError("bounded APRS outbound queue is full")
        packets = tuple(
            OutboundPacket(self.service_callsign, peer, fragment.body)
            for fragment in fragments
        )
        self._burst_queue.append(
            _BurstTx(
                peer=peer,
                transaction_id=transaction_id,
                fragments=fragments,
                packets=packets,
                priority=1 if proactive else 0,
                order=self._burst_order,
                delivery=delivery,
                response_batch=response_batch,
                response_supersedable=response_supersedable,
            )
        )
        self._burst_order += 1
        return transaction_id

    def _supersede_stale_response_batches(
        self, peer: str, current_batch: tuple[str, str]
    ) -> None:
        super()._supersede_stale_response_batches(peer, current_batch)
        stale = {
            tx.response_batch
            for tx in self._burst_queue
            if tx.peer == peer
            and tx.response_batch is not None
            and tx.response_batch != current_batch
            and tx.response_supersedable
        }
        active = self._burst_active.get(peer)
        if (
            active is not None
            and active.response_batch is not None
            and active.response_batch != current_batch
            and active.response_supersedable
        ):
            stale.add(active.response_batch)
        if not stale:
            return
        self._burst_queue = [
            tx for tx in self._burst_queue if tx.response_batch not in stale
        ]
        active = self._burst_active.get(peer)
        if active is not None and active.response_batch in stale:
            del self._burst_active[peer]

    def _confirm_inbound(
        self, peer: str, message_id: str | None, *, accepted: bool = True
    ) -> None:
        if accepted:
            return
        super()._confirm_inbound(peer, message_id, accepted=False)

    def _complete_outbound(self, peer: str, tx: _BurstTx) -> None:
        if self._burst_active.get(peer) is tx:
            del self._burst_active[peer]
        if tx.delivery is not None:
            self.core.mark_aprs_delivered(*tx.delivery)

    def _fail_outbound(self, peer: str, tx: _BurstTx) -> None:
        if self._burst_active.get(peer) is tx:
            del self._burst_active[peer]
        if tx.delivery is not None:
            self.core.mark_aprs_failed(*tx.delivery)
        self.failed_packets.extend(tx.packets)
        del self.failed_packets[: -self.config.event_history_capacity]

    def _refresh_aprs_presence(self, peer: str) -> None:
        if self.router is None:
            return
        callsign = normalize_callsign(peer, "APRS source")
        self.router.presence.set_aprs(callsign, peer)

    def _compact_stored_result(self, peer: str, transaction_id: str, now: float) -> None:
        replay = self.replay.get(peer, transaction_id, now)
        if replay is None:
            return
        if not isinstance(decode_frame(replay.request), SendMessage):
            return
        if len(replay.responses) != 1 or not isinstance(
            decode_frame(replay.responses[0]), Stored
        ):
            return
        response_batch = (peer, transaction_id)
        self._burst_queue = [
            tx for tx in self._burst_queue if tx.response_batch != response_batch
        ]
        active = self._burst_active.get(peer)
        if active is not None and active.response_batch == response_batch:
            del self._burst_active[peer]
        self._immediate.append(
            OutboundPacket(
                self.service_callsign,
                peer,
                encode_stored(transaction_id),
            )
        )

    def receive(self, peer: str, body: str, *, now: float | None = None) -> str:
        now = self.clock() if now is None else now
        try:
            peer = self.validate_peer(peer)
        except CarriageError:
            return "ignored"

        control = parse_burst_control(body)
        if control is not None:
            kind, transaction_id, missing = control
            tx = self._burst_active.get(peer)
            if tx is None or tx.transaction_id != transaction_id:
                return "ignored"
            if kind == "ack":
                self._refresh_aprs_presence(peer)
                self._complete_outbound(peer, tx)
                return "acknowledged"
            valid_missing = frozenset(
                index for index in missing if index < len(tx.fragments)
            )
            if not valid_missing:
                return "ignored"
            self._refresh_aprs_presence(peer)
            tx.requested = valid_missing
            tx.repair_active = True
            tx.repair_indices = valid_missing
            return "repair-requested"

        try:
            fragment = parse_fragment(body)
        except (CarriageError, TypeError):
            return super().receive(peer, body, now=now)

        key = (peer, fragment.transaction_id)
        progress = self._rx_progress.get(key)
        if progress is None or progress.total != fragment.total:
            progress = _RxProgress(fragment.total)
            self._rx_progress[key] = progress
        progress.received.add(fragment.index)
        if fragment.index == fragment.total - 1:
            progress.saw_final = True
        grace = self.final_fragment_grace if progress.saw_final else self.repair_grace
        progress.deadline = now + min(grace, self.repair_grace)

        disposition = super().receive(peer, body, now=now)
        if disposition in {"completed", "replayed"}:
            self._immediate.append(
                OutboundPacket(
                    self.service_callsign,
                    peer,
                    encode_burst_ack(fragment.transaction_id),
                )
            )
            self._compact_stored_result(peer, fragment.transaction_id, now)
        if disposition in {"completed", "replayed", "invalid", "conflict"}:
            self._rx_progress.pop(key, None)
        return disposition

    def poll(self, *, now: float | None = None) -> list[OutboundPacket]:
        now = self.clock() if now is None else now
        packets, self._immediate = self._immediate, []

        for (peer, transaction_id), progress in tuple(self._rx_progress.items()):
            if now < progress.deadline:
                continue
            missing = progress.missing
            if not missing:
                self._rx_progress.pop((peer, transaction_id), None)
                continue
            packets.append(
                OutboundPacket(
                    self.service_callsign,
                    peer,
                    encode_missing(transaction_id, missing),
                )
            )
            grace = self.final_fragment_grace if progress.saw_final else self.repair_grace
            progress.deadline = now + min(grace, self.repair_grace)

        for peer, tx in tuple(self._burst_active.items()):
            indices: tuple[int, ...] | None = None
            if tx.requested is not None:
                indices = tuple(sorted(tx.requested))
                tx.requested = None
            elif tx.deadline and now >= tx.deadline:
                if tx.repair_active:
                    if tx.repair_indices:
                        indices = tuple(sorted(tx.repair_indices))
                    else:
                        self._fail_outbound(peer, tx)
                        continue
                else:
                    indices = tuple(range(len(tx.fragments)))
            if indices is None:
                continue
            if tx.attempts >= self.config.max_attempts:
                self._fail_outbound(peer, tx)
                continue
            if now - self._last_send[peer] < self.config.min_interval:
                tx.requested = frozenset(indices)
                continue
            packets.extend(tx.packets[index] for index in indices)
            tx.attempts += 1
            tx.deadline = now + self.config.ack_timeout
            self._last_send[peer] = now

        candidates = sorted(self._burst_queue, key=lambda tx: (tx.priority, tx.order))
        for tx in candidates:
            if tx.peer in self._burst_active:
                continue
            if now - self._last_send[tx.peer] < self.config.min_interval:
                continue
            self._burst_queue.remove(tx)
            self._burst_active[tx.peer] = tx
            tx.attempts = 1
            tx.deadline = now + self.config.ack_timeout
            packets.extend(tx.packets)
            self._last_send[tx.peer] = now

        self.reassembly.expire(now)
        self.replay.expire(now)
        self._expire_activity(now)
        return packets
