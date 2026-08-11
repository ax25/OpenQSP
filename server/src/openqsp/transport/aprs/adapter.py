"""Deterministic APRS reliability, activity, and ServerCore bridge."""

from __future__ import annotations

import heapq
import re
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from openqsp.protocol import (
    GetBulletin,
    GetCapabilities,
    GetNewBulletins,
    GetNewMessages,
    Message,
    SendMessage,
    decode_frame,
    encode_frame,
    normalize_callsign,
)
from openqsp.server import ServerCore

from .carriage import (
    APRSFragment,
    CarriageError,
    base36,
    fragment_frame,
    parse_fragment,
)
from .state import Reassembler, ReplayCache, TransactionConflict

SERVICE_CALLSIGN = "OPENQSP"  # Backwards-compatible profile default.
_PEER_RE = re.compile(r"[A-Z0-9]{3,12}(?:-[0-9]{1,2})?")
_ACK_RE = re.compile(r"ack([0-9A-Z]{1,5})")


@dataclass(frozen=True)
class AdapterConfig:
    ack_timeout: float = 8.0
    max_attempts: int = 3
    min_interval: float = 2.0
    activity_timeout: float = 600.0
    reassembly_ttl: float = 120.0
    replay_ttl: float = 600.0
    max_reassemblies: int = 128
    max_replays: int = 256
    max_replays_per_peer: int = 16
    queue_capacity: int = 512
    transaction_id_space: int = 36**3
    max_activity_peers: int = 256
    event_history_capacity: int = 512

    def __post_init__(self) -> None:
        if (
            self.ack_timeout <= 0
            or self.max_attempts <= 0
            or self.activity_timeout <= 0
        ):
            raise ValueError("timeouts and attempts must be positive")
        if self.min_interval < 0 or self.queue_capacity <= 0:
            raise ValueError("rate interval must be non-negative and queue bounded")
        if not 1 <= self.transaction_id_space <= 36**3:
            raise ValueError("transaction ID space must be between 1 and 46656")
        if self.max_activity_peers <= 0 or self.event_history_capacity <= 0:
            raise ValueError("activity and event-history bounds must be positive")


@dataclass(frozen=True)
class OutboundPacket:
    source: str
    destination: str
    body: str
    is_ack: bool = False


@dataclass(order=True)
class _Queued:
    priority: int
    order: int
    peer: str = field(compare=False)
    fragment: APRSFragment = field(compare=False)


@dataclass
class _Pending:
    packet: OutboundPacket
    attempts: int
    deadline: float
    priority: int


class APRSAdapter:
    """Synchronous state machine; callers inject packets and advance a clock."""

    def __init__(
        self,
        core: ServerCore,
        *,
        config: AdapterConfig | None = None,
        clock: Callable[[], float] | None = None,
        service_callsign: str = SERVICE_CALLSIGN,
    ) -> None:
        self.core, self.config = core, config or AdapterConfig()
        self.service_callsign = self.validate_peer(service_callsign.upper())
        self.clock = clock or time.monotonic
        self.reassembly = Reassembler(
            ttl=self.config.reassembly_ttl, max_entries=self.config.max_reassemblies
        )
        self.replay = ReplayCache(
            ttl=self.config.replay_ttl,
            max_entries=self.config.max_replays,
            max_per_peer=self.config.max_replays_per_peer,
        )
        self._queue: list[_Queued] = []
        self._pending: dict[tuple[str, str], _Pending] = {}
        self._immediate: list[OutboundPacket] = []
        self._next_transaction: defaultdict[str, int] = defaultdict(int)
        self._next_message: defaultdict[str, int] = defaultdict(int)
        self._activity: dict[str, tuple[str, float]] = {}
        self._last_send: defaultdict[str, float] = defaultdict(lambda: float("-inf"))
        self._order = 0
        self.completed_transactions: list[tuple[str, str]] = []
        self.failed_packets: list[OutboundPacket] = []
        core.add_message_listener(self._on_message)

    @staticmethod
    def validate_peer(peer: str) -> str:
        if not isinstance(peer, str) or _PEER_RE.fullmatch(peer) is None:
            raise CarriageError("invalid APRS source address")
        ssid = peer.partition("-")[2]
        if ssid and int(ssid) > 15:
            raise CarriageError("APRS SSID must be between 0 and 15")
        return peer

    def _allocate(self, peer: str, *, transaction: bool) -> str:
        counters = self._next_transaction if transaction else self._next_message
        width, space = (
            (3, self.config.transaction_id_space) if transaction else (2, 36**2)
        )
        active_transactions = self._active_transactions(peer) if transaction else set()
        active_messages = self._active_message_ids(peer) if not transaction else set()
        for _ in range(space):
            value = counters[peer] % space
            counters[peer] = value + 1
            candidate = base36(value, width)
            if (
                transaction
                and candidate not in active_transactions
                or not transaction
                and candidate not in active_messages
            ):
                return candidate
        raise OverflowError("peer APRS identifier space exhausted")

    def _active_transactions(self, peer: str) -> set[str]:
        """Return bounded outbound TTTs still queued or awaiting an APRS ACK."""
        active = {
            item.fragment.transaction_id for item in self._queue if item.peer == peer
        }
        for (pending_peer, _), pending in self._pending.items():
            if pending_peer != peer:
                continue
            try:
                active.add(parse_fragment(pending.packet.body).transaction_id)
            except CarriageError:
                # Pending application packets are always fragments.  Keeping a
                # malformed internal packet out of allocation state is safe and
                # lets its normal retry/failure bookkeeping release it.
                continue
        return active

    def _active_message_ids(self, peer: str) -> set[str]:
        active = {
            item.fragment.message_id
            for item in self._queue
            if item.peer == peer and item.fragment.message_id is not None
        }
        active.update(
            message_id
            for pending_peer, message_id in self._pending
            if pending_peer == peer
        )
        return active

    def queue_frame(self, peer: str, frame: bytes, *, proactive: bool = False) -> str:
        self.validate_peer(peer)
        transaction_id = self._allocate(peer, transaction=True)
        fragments = fragment_frame(frame, transaction_id)
        if len(self._queue) + len(fragments) > self.config.queue_capacity:
            raise OverflowError("bounded APRS outbound queue is full")
        priority = 1 if proactive else 0
        for fragment in fragments:
            message_id = self._allocate(peer, transaction=False)
            queued = APRSFragment(
                fragment.transaction_id,
                fragment.index,
                fragment.total,
                fragment.data,
                message_id,
            )
            heapq.heappush(self._queue, _Queued(priority, self._order, peer, queued))
            self._order += 1
        return transaction_id

    def receive(self, peer: str, body: str, *, now: float | None = None) -> str:
        """Accept one APRS message body; returns a stable disposition string."""
        now = self.clock() if now is None else now
        try:
            peer = self.validate_peer(peer)
        except CarriageError:
            return "ignored"
        ack = _ACK_RE.fullmatch(body)
        if ack is not None:
            return (
                "acknowledged"
                if self._pending.pop((peer, ack.group(1)), None)
                else "ignored"
            )
        try:
            fragment = parse_fragment(body)
        except (CarriageError, TypeError):
            return "ignored"
        if fragment.message_id is not None:
            self._immediate.append(
                OutboundPacket(
                    self.service_callsign, peer, f"ack{fragment.message_id}", True
                )
            )
        try:
            frame = self.reassembly.add(peer, fragment, now)
        except TransactionConflict:
            return "conflict"
        except CarriageError:
            return "invalid"
        if frame is None:
            return "fragment"
        cached = self.replay.get(peer, fragment.transaction_id, now)
        if cached is not None:
            if cached.request != frame:
                return "conflict"
            for response in cached.responses:
                self.queue_frame(peer, response)
            return "replayed"
        # Reassembly already validates via the production decoder; decoding here
        # classifies it as a valid client request before activity is refreshed.
        request = decode_frame(frame)
        if not isinstance(
            request,
            (
                SendMessage,
                GetNewMessages,
                GetNewBulletins,
                GetBulletin,
                GetCapabilities,
            ),
        ):
            return "invalid"
        callsign = normalize_callsign(peer, "APRS source")
        responses = tuple(self.core.handle_frame(callsign, frame))
        self.replay.put(peer, fragment.transaction_id, frame, responses, now)
        self._expire_activity(now)
        if (
            peer not in self._activity
            and len(self._activity) >= self.config.max_activity_peers
        ):
            oldest = min(self._activity, key=lambda item: self._activity[item][1])
            del self._activity[oldest]
        self._activity[peer] = (callsign, now)
        self.completed_transactions.append((peer, fragment.transaction_id))
        del self.completed_transactions[: -self.config.event_history_capacity]
        for response in responses:
            self.queue_frame(peer, response)
        return "completed"

    def poll(self, *, now: float | None = None) -> list[OutboundPacket]:
        """Return packets currently permitted by ACK/retry and rate policies."""
        now = self.clock() if now is None else now
        packets, self._immediate = self._immediate, []
        for key, pending in tuple(self._pending.items()):
            if now < pending.deadline:
                continue
            if pending.attempts >= self.config.max_attempts:
                self.failed_packets.append(pending.packet)
                del self.failed_packets[: -self.config.event_history_capacity]
                del self._pending[key]
            elif (
                now - self._last_send[pending.packet.destination]
                >= self.config.min_interval
            ):
                pending.attempts += 1
                pending.deadline = now + self.config.ack_timeout
                self._last_send[pending.packet.destination] = now
                packets.append(pending.packet)
        if self._queue:
            item = self._queue[0]
            peer_has_pending = any(peer == item.peer for peer, _ in self._pending)
            if (
                not peer_has_pending
                and now - self._last_send[item.peer] >= self.config.min_interval
            ):
                heapq.heappop(self._queue)
                packet = OutboundPacket(
                    self.service_callsign, item.peer, item.fragment.body
                )
                self._pending[(item.peer, item.fragment.message_id or "")] = _Pending(
                    packet, 1, now + self.config.ack_timeout, item.priority
                )
                self._last_send[item.peer] = now
                packets.append(packet)
        self.reassembly.expire(now)
        self.replay.expire(now)
        self._expire_activity(now)
        return packets

    def is_active(self, peer: str, *, now: float | None = None) -> bool:
        now = self.clock() if now is None else now
        state = self._activity.get(peer)
        if state is None:
            return False
        if now - state[1] >= self.config.activity_timeout:
            del self._activity[peer]
            return False
        return True

    def _expire_activity(self, now: float) -> None:
        for peer, (_, active_at) in tuple(self._activity.items()):
            if now - active_at >= self.config.activity_timeout:
                del self._activity[peer]

    def _on_message(self, message: Message) -> None:
        now = self.clock()
        for peer, (callsign, active_at) in tuple(self._activity.items()):
            if (
                callsign == message.recipient
                and now - active_at < self.config.activity_timeout
            ):
                self.queue_frame(
                    peer, encode_frame(message, unsolicited=True), proactive=True
                )

    @property
    def queued_count(self) -> int:
        return len(self._queue)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def close(self) -> None:
        self.core.remove_message_listener(self._on_message)

    def connection_lost(self) -> None:
        """Discard link delivery state that cannot be ACK-correlated after reconnect.

        Reassembly and replay are deliberately retained: both are peer/TTT
        scoped, TTL bounded, independent of one APRS-IS socket, and let a peer
        safely finish or replay a request after the service reconnects.
        """
        self._queue.clear()
        self._pending.clear()
        self._immediate.clear()
