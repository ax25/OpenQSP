"""Guard completed selective APRS bursts against late duplicate fragments."""

from __future__ import annotations

from .adapter import OutboundPacket
from .carriage import CarriageError, parse_fragment
from .selective_burst import (
    APRSAdapter as _BaseSelectiveBurstAPRSAdapter,
    encode_burst_ack,
)


class APRSAdapter(_BaseSelectiveBurstAPRSAdapter):
    """Selective-burst adapter that never reopens a completed RX transaction."""

    def receive(self, peer: str, body: str, *, now: float | None = None) -> str:
        current = self.clock() if now is None else now
        try:
            normalized_peer = self.validate_peer(peer)
            fragment = parse_fragment(body)
        except (CarriageError, TypeError):
            return super().receive(peer, body, now=now)

        key = (normalized_peer, fragment.transaction_id)
        replay = self.replay.get(normalized_peer, fragment.transaction_id, current)
        if replay is not None:
            # The complete Core request is already in replay storage. A late RF
            # duplicate must not create a fresh _RxProgress containing only that
            # fragment, otherwise poll() will repeatedly NACK all other indexes.
            self._rx_progress.pop(key, None)
            self._immediate.append(
                OutboundPacket(
                    self.service_callsign,
                    normalized_peer,
                    encode_burst_ack(fragment.transaction_id),
                )
            )
            self._compact_stored_result(
                normalized_peer, fragment.transaction_id, current
            )
            return "replayed"

        return super().receive(normalized_peer, body, now=current)
