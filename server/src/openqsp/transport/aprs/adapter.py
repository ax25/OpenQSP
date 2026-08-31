"""Deterministic APRS reliability, activity, and ServerCore bridge."""

from __future__ import annotations

import heapq
import re
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from openqsp.protocol import (
    Error,
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
from openqsp.server import DeliveryRouter, ServerCore

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
_MESSAGE_ID_RE = re.compile(r"\{([0-9A-Z]{1,5})$")


@dataclass(frozen=True)
class AdapterConfig:
    ack_timeout: float = 31.0
    max_attempts: int = 5
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
        if self.min_interval < 0 or self.config.queue_capacity <= 0:
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
    delivery: tuple[str, int] | None = field(default=None, compare=False)
    response_batch: tuple[str, str] | None = field(default=None, compare=False)
    response_supersedable: bool = field(default=True, compare=False)


@dataclass
class _Pending:
    packet: OutboundPacket
    attempts: int
    deadline: float
    priority: int
    transaction_id: str
    delivery: tuple[str, int] | None = None
    response_batch: tuple[str, str] | None = None
    response_supersedable: bool = True


class APRSAdapter:
    """Synchronous state machine; callers inject packets and advance a clock."""

    def __init__(
        self,
        core: ServerCore,
        *,
        config: AdapterConfig | None = None,
        clock: Callable[[], float] | None = None,
        service_callsign: str = SERVICE_CALLSIGN,
        router: DeliveryRouter | None = None,
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
        self.router = router
        if router is not None:
            router.aprs_delivery = self.deliver_message

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
            heapq.heappush(
                self._queue,
                _Queued(
                    priority,
                    self._order,
                    peer,
                    queued,
                    delivery,
                    response_batch,
                    response_supersedable,
                ),
            )
            self._order += 1
        return transaction_id

    def _supersede_stale_response_batches(
        self, peer: str, current_batch: tuple[str, str]
    ) -> None:
        """Drop only replaceable older responses for a peer."""
        stale_batches = {
            item.response_batch
            for item in self._queue
            if item.peer == peer
            and item.response_batch is not None
            and item.response_batch != current_batch
            and item.response_supersedable
        }
        stale_batches.update(
            pending.response_batch
            for (pending_peer, _), pending in self._pending.items()
            if pending_peer == peer
            and pending.response_batch is not None
            and pending.response_batch != current_batch
            and pending.response_supersedable
        )
        if not stale_batches:
            return
        self._queue = [
            item for item in self._queue if item.response_batch not in stale_batches
        ]
        heapq.heapify(self._queue)
        for key, pending in tuple(self._pending.items()):
            if key[0] == peer and pending.response_batch in stale_batches:
                del self._pending[key]

    def _confirm_inbound(
        self, peer: str, message_id: str | None, *, accepted: bool = True
    ) -> None:
        if message_id is None:
            return
        prefix = "ack" if accepted else "rej"
        self._immediate.append(
            OutboundPacket(
                self.service_callsign,
                peer,
                f"{prefix}{message_id}",
                accepted,
            )
        )

    @staticmethod
    def _responses_accepted(responses: tuple[bytes, ...]) -> bool:
        return bool(responses) and not any(
            isinstance(decode_frame(response), Error) for response in responses
        )

    def receive(self, peer: str, body: str, *, now: float | None = None) -> str:
        """Accept one APRS message body; returns a stable disposition string."""
        now = self.clock() if now is None else now
        try:
            peer = self.validate_peer(peer)
        except CarriageError:
            return "ignored"
        ack = _ACK_RE.fullmatch(body)
        if ack is not None:
            pending = self._pending.pop((peer, ack.group(1)), None)
            if pending is None:
                return "ignored"
            transaction_outstanding = any(
                item.peer == peer
                and item.fragment.transaction_id == pending.transaction_id
                for item in self._queue
            ) or any(
                other_peer == peer and other.transaction_id == pending.transaction_id
                for (other_peer, _), other in self._pending.items()
            )
            if pending.delivery is not None and not transaction_outstanding:
                self.core.mark_aprs_delivered(*pending.delivery)
            return "acknowledged"

        message_id_match = _MESSAGE_ID_RE.search(body)
        inbound_message_id = (
            message_id_match.group(1) if message_id_match is not None else None
        )
        try:
            fragment = parse_fragment(body)
        except (CarriageError, TypeError):
            return "ignored"
        try:
            frame = self.reassembly.add(peer, fragment, now)
        except TransactionConflict:
            self._confirm_inbound(peer, inbound_message_id, accepted=False)
            return "conflict"
        except CarriageError:
            self._confirm_inbound(peer, inbound_message_id, accepted=False)
            return "invalid"
        if frame is None:
            self._confirm_inbound(peer, inbound_message_id)
            return "fragment"

        response_batch = (peer, fragment.transaction_id)
        cached = self.replay.get(peer, fragment.transaction_id, now)
        if cached is not None:
            if cached.request != frame:
                self._confirm_inbound(peer, inbound_message_id, accepted=False)
                return "conflict"
            cached_request = decode_frame(cached.request)
            response_supersedable = not isinstance(cached_request, SendMessage)
            self._activate_aprs_if_accepted(peer, cached.responses)
            self._supersede_stale_response_batches(peer, response_batch)
            if isinstance(cached_request, SendMessage) and inbound_message_id is not None:
                self._confirm_inbound(
                    peer,
                    inbound_message_id,
                    accepted=self._responses_accepted(cached.responses),
                )
                return "replayed"
            self._confirm_inbound(peer, inbound_message_id)
            for response in cached.responses:
                self.queue_frame(
                    peer,
                    response,
                    response_batch=response_batch,
                    response_supersedable=response_supersedable,
                )
            return "replayed"

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
            self._confirm_inbound(peer, inbound_message_id, accepted=False)
            return "invalid"
        if not isinstance(request, SendMessage):
            self._confirm_inbound(peer, inbound_message_id)

        callsign = normalize_callsign(peer, "APRS source")
        responses = tuple(self.core.handle_frame(callsign, frame))
        response_supersedable = not isinstance(request, SendMessage)
        self._activate_aprs_if_accepted(peer, responses)
        self._supersede_stale_response_batches(peer, response_batch)
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

        if isinstance(request, SendMessage) and inbound_message_id is not None:
            self._confirm_inbound(
                peer,
                inbound_message_id,
                accepted=self._responses_accepted(responses),
            )
            return "completed"

        for response in responses:
            decoded = decode_frame(response)
            delivery = (
                (decoded.recipient, decoded.sequence)
                if isinstance(decoded, Message)
                else None
            )
            self.queue_frame(
                peer,
                response,
                delivery=delivery,
                response_batch=response_batch,
                response_supersedable=response_supersedable,
            )
            if delivery is not None:
                self.core.mark_aprs_pending(*delivery)
        return "completed"

    def _activate_aprs_if_accepted(
        self, peer: str, responses: tuple[bytes, ...]
    ) -> None:
        """Select APRS only after Core accepts a valid client operation."""
        if self.router is None or not responses:
            return
        if any(isinstance(decode_frame(response), Error) for response in responses):
            return
        callsign = normalize_callsign(peer, "APRS source")
        self.router.presence.set_aprs(callsign, peer)

    def _fail_transaction(self, peer: str, pending: _Pending) -> None:
        """Abort a failed frame and the rest of its request-response batch."""
        transaction_id = pending.transaction_id
        response_batch = pending.response_batch
        abandoned_deliveries: set[tuple[str, int]] = set()
        if pending.delivery is not None:
            abandoned_deliveries.add(pending.delivery)

        def belongs_to_failed_work(item: _Queued) -> bool:
            if item.peer != peer:
                return False
            if item.fragment.transaction_id == transaction_id:
                return True
            return response_batch is not None and item.response_batch == response_batch

        retained: list[_Queued] = []
        for item in self._queue:
            if belongs_to_failed_work(item):
                if item.delivery is not None:
                    abandoned_deliveries.add(item.delivery)
            else:
                retained.append(item)
        self._queue = retained
        heapq.heapify(self._queue)

        for key, other in tuple(self._pending.items()):
            if key[0] != peer:
                continue
            same_transaction = other.transaction_id == transaction_id
            same_batch = (
                response_batch is not None and other.response_batch == response_batch
            )
            if same_transaction or same_batch:
                if other.delivery is not None:
                    abandoned_deliveries.add(other.delivery)
                del self._pending[key]

        for delivery in abandoned_deliveries:
            self.core.mark_aprs_failed(*delivery)

    def poll(self, *, now: float | None = None) -> list[OutboundPacket]:
        """Return packets currently permitted by ACK/retry and rate policies."""
        now = self.clock() if now is None else now
        packets, self._immediate = self._immediate, []
        for key, pending in tuple(self._pending.items()):
            if self._pending.get(key) is not pending:
                continue
            if now < pending.deadline:
                continue
            if pending.attempts >= self.config.max_attempts:
                self.failed_packets.append(pending.packet)
                del self.failed_packets[: -self.config.event_history_capacity]
                self._fail_transaction(key[0], pending)
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
                    packet,
                    1,
                    now + self.config.ack_timeout,
                    item.priority,
                    item.fragment.transaction_id,
                    item.delivery,
                    item.response_batch,
                    item.response_supersedable,
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

    def deliver_message(self, message: Message, endpoint: str) -> bool:
        """Queue a routed message for an explicitly selected APRS endpoint."""
        self.queue_frame(
            endpoint,
            encode_frame(message, unsolicited=True),
            proactive=True,
            delivery=(message.recipient, message.sequence),
        )
        self.core.mark_aprs_pending(message.recipient, message.sequence)
        return True

    @property
    def queued_count(self) -> int:
        return len(self._queue)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def close(self) -> None:
        if self.router is not None and self.router.aprs_delivery == self.deliver_message:
            self.router.aprs_delivery = None

    def connection_lost(self) -> None:
        """Discard link delivery state that cannot be ACK-correlated after reconnect.

        Reassembly and replay are deliberately retained: both are peer/TTT
        scoped, TTL bounded, independent of one APRS-IS socket, and let a peer
        safely finish or replay a request after the service reconnects.
        """
        abandoned = {
            item.delivery for item in self._queue if item.delivery is not None
        } | {
            pending.delivery
            for pending in self._pending.values()
            if pending.delivery is not None
        }
        self._queue.clear()
        self._pending.clear()
        self._immediate.clear()
        for delivery in abandoned:
            self.core.mark_aprs_failed(*delivery)
