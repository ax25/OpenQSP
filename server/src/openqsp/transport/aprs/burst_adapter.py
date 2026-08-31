"""Burst-oriented APRS outbound scheduling.

This keeps one logical OpenQSP transaction in flight per peer, but sends all
fragments belonging to that transaction together. Fragment ACKs still clear
individual pending packets, so retries retransmit only the fragments whose ACKs
were not received.
"""

from __future__ import annotations

import heapq
from collections import defaultdict

from .adapter import OutboundPacket, _Pending
from .commit_adapter import APRSAdapter as _CommitAPRSAdapter


class APRSAdapter(_CommitAPRSAdapter):
    """APRS adapter with burst-per-transaction outbound scheduling."""

    def poll(self, *, now: float | None = None) -> list[OutboundPacket]:
        now = self.clock() if now is None else now
        packets, self._immediate = self._immediate, []

        # First fail transactions whose missing fragments exhausted retries.
        for key, pending in tuple(self._pending.items()):
            if self._pending.get(key) is not pending or now < pending.deadline:
                continue
            if pending.attempts < self.config.max_attempts:
                continue
            self.failed_packets.append(pending.packet)
            del self.failed_packets[: -self.config.event_history_capacity]
            self._fail_transaction(key[0], pending)

        # Remaining expired pending packets are exactly the fragments whose ACK
        # was not seen. Retransmit those selectively as one retry burst per peer.
        due_by_peer: dict[str, list[_Pending]] = defaultdict(list)
        for (peer, _), pending in tuple(self._pending.items()):
            if now < pending.deadline:
                continue
            if (
                now - self._last_send[pending.packet.destination]
                < self.config.min_interval
            ):
                continue
            due_by_peer[peer].append(pending)

        for peer, due in due_by_peer.items():
            sent = False
            for pending in due:
                if pending not in self._pending.values():
                    continue
                pending.attempts += 1
                pending.deadline = now + self.config.ack_timeout
                packets.append(pending.packet)
                sent = True
            if sent:
                self._last_send[peer] = now

        # Launch at most one OpenQSP transaction per peer at a time. Within that
        # transaction, however, hand every fragment to APRS-IS in the same poll
        # call so the downstream IGate/TNC can transmit it as a burst.
        while self._queue:
            pending_peers = {peer for peer, _ in self._pending}
            candidate = next(
                (
                    item
                    for item in sorted(self._queue)
                    if item.peer not in pending_peers
                    and now - self._last_send[item.peer] >= self.config.min_interval
                ),
                None,
            )
            if candidate is None:
                break

            peer = candidate.peer
            transaction_id = candidate.fragment.transaction_id
            burst = [
                item
                for item in self._queue
                if item.peer == peer
                and item.fragment.transaction_id == transaction_id
            ]
            self._queue = [item for item in self._queue if item not in burst]
            heapq.heapify(self._queue)
            burst.sort(key=lambda item: item.order)

            for item in burst:
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
                packets.append(packet)
            self._last_send[peer] = now

        self.reassembly.expire(now)
        self.replay.expire(now)
        self._expire_activity(now)
        return packets
