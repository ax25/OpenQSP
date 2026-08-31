"""Backward-compatible APRS SEND_MESSAGE commit-ACK adapter."""

from __future__ import annotations

from openqsp.protocol import (
    GetBulletin,
    GetCapabilities,
    GetNewBulletins,
    GetNewMessages,
    Message,
    SendMessage,
    decode_frame,
    normalize_callsign,
)

from .adapter import APRSAdapter as _BaseAPRSAdapter
from .adapter import _ACK_RE, _MESSAGE_ID_RE
from .carriage import CarriageError, parse_fragment
from .commit_ack import requested as commit_ack_requested
from .state import TransactionConflict


class APRSAdapter(_BaseAPRSAdapter):
    """APRS adapter with opt-in durable ACKs for SEND_MESSAGE.

    Clients opt in by using a C-prefixed APRS message ID after discovering the
    APRS_COMMIT_ACK capability. Legacy IDs retain immediate transport ACK plus
    the normal OpenQSP STORED/ERROR response, so old and new clients can coexist.
    """

    def receive(self, peer: str, body: str, *, now: float | None = None) -> str:
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
        commit_ack = commit_ack_requested(inbound_message_id)

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
            if isinstance(cached_request, SendMessage) and commit_ack:
                self._confirm_inbound(
                    peer,
                    inbound_message_id,
                    accepted=self._responses_accepted(cached.responses),
                )
                return "replayed"

            # Legacy path: transport ACK immediately and replay the original
            # STORED/ERROR response just as the pre-commit-ACK profile did.
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

        # Non-SEND operations and legacy SEND_MESSAGE IDs keep normal APRS
        # transport ACK semantics. Commit-ACK SEND_MESSAGE delays the ACK until
        # after ServerCore has durably accepted the operation.
        if not isinstance(request, SendMessage) or not commit_ack:
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

        if isinstance(request, SendMessage) and commit_ack:
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
