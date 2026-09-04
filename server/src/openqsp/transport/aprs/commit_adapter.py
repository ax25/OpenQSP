"""Backward-compatible APRS SEND_MESSAGE commit-ACK adapter."""

from __future__ import annotations

import heapq

from openqsp.protocol import (
    GetBulletin,
    GetCapabilities,
    GetMessage,
    GetNewBulletins,
    GetNewMessages,
    Message,
    SendMessage,
    Stored,
    decode_frame,
    normalize_callsign,
)

from .adapter import _ACK_RE, _MESSAGE_ID_RE
from .adapter import APRSAdapter as _BaseAPRSAdapter
from .carriage import CarriageError, parse_fragment
from .commit_ack import requested as commit_ack_requested
from .state import TransactionConflict


class APRSAdapter(_BaseAPRSAdapter):
    """APRS adapter with opt-in durable ACKs for SEND_MESSAGE.

    After discovering the APRS_COMMIT_ACK capability, clients opt in by using a
    C-prefixed APRS message ID. Legacy IDs preserve the pre-extension behavior:
    they are ACKed as soon as the APRS packet is received and SEND_MESSAGE keeps
    its normal OpenQSP STORED/ERROR response.

    For an opted-in SEND_MESSAGE, non-final Q1 fragments are ACKed normally,
    while the fragment that completes the Core request is ACKed only after Core
    returns STORED. A failed Core send is answered with APRS REJ instead. The
    same rule is applied to replayed Q1 transactions, so a lost commit ACK can
    be recovered without executing SEND_MESSAGE twice.
    """

    @staticmethod
    def _send_was_stored(responses: tuple[bytes, ...]) -> bool:
        return len(responses) == 1 and isinstance(decode_frame(responses[0]), Stored)

    def _reconcile_message_cursor(self, peer: str, callsign: str, since: int) -> None:
        """Treat the client's cursor as proof that older deliveries were received.

        APRS ACK loss must not override a newer GET_NEW_MESSAGES cursor. If the
        client asks for messages after N, any queued or ACK-pending delivery for
        that same mailbox at sequence <= N is obsolete and must not be sent
        again. Recording it as delivered also repairs the stale transport state.
        """
        confirmed: set[tuple[str, int]] = set()

        retained = []
        for item in self._queue:
            delivery = item.delivery
            if (
                item.peer == peer
                and delivery is not None
                and delivery[0] == callsign
                and delivery[1] <= since
            ):
                confirmed.add(delivery)
            else:
                retained.append(item)
        if len(retained) != len(self._queue):
            self._queue = retained
            heapq.heapify(self._queue)

        for key, pending in tuple(self._pending.items()):
            delivery = pending.delivery
            if (
                key[0] == peer
                and delivery is not None
                and delivery[0] == callsign
                and delivery[1] <= since
            ):
                confirmed.add(delivery)
                del self._pending[key]

        for delivery in confirmed:
            self.core.mark_aprs_delivered(*delivery)

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

        # Legacy APRS message IDs retain the historical transport contract:
        # ACK first, then attempt to parse/process the OpenQSP payload.
        if inbound_message_id is not None and not commit_ack:
            self._confirm_inbound(peer, inbound_message_id)

        try:
            fragment = parse_fragment(body)
        except (CarriageError, TypeError):
            if commit_ack:
                self._confirm_inbound(peer, inbound_message_id, accepted=False)
            return "ignored"
        try:
            frame = self.reassembly.add(peer, fragment, now)
        except TransactionConflict:
            if commit_ack:
                self._confirm_inbound(peer, inbound_message_id, accepted=False)
            return "conflict"
        except CarriageError:
            if commit_ack:
                self._confirm_inbound(peer, inbound_message_id, accepted=False)
            return "invalid"

        # A C-prefixed ID on a non-final Q1 fragment is still an ordinary
        # fragment-level ACK. Only the fragment completing SEND_MESSAGE carries
        # the durable commit meaning.
        if frame is None:
            if commit_ack:
                self._confirm_inbound(peer, inbound_message_id)
            return "fragment"

        response_batch = (peer, fragment.transaction_id)
        cached = self.replay.get(peer, fragment.transaction_id, now)
        if cached is not None:
            if cached.request != frame:
                if commit_ack:
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
                    accepted=self._send_was_stored(cached.responses),
                )
                return "replayed"

            if commit_ack:
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
                GetMessage,
            ),
        ):
            if commit_ack:
                self._confirm_inbound(peer, inbound_message_id, accepted=False)
            return "invalid"

        # C-prefixed IDs are only special for SEND_MESSAGE. If a future/new
        # client uses one on another supported operation, preserve normal ACK
        # semantics rather than silently withholding the transport ACK.
        if commit_ack and not isinstance(request, SendMessage):
            self._confirm_inbound(peer, inbound_message_id)

        callsign = normalize_callsign(peer, "APRS source")
        if isinstance(request, GetNewMessages):
            self._reconcile_message_cursor(peer, callsign, request.since)

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
                accepted=self._send_was_stored(responses),
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
