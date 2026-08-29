"""Authoritative user presence and transport-neutral delivery routing."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from openqsp.protocol import Message, validate_callsign


class ActiveTransport(str, Enum):
    WEBSOCKET = "websocket"
    APRS = "aprs"


@dataclass(frozen=True)
class UserPresence:
    callsign: str
    active_transport: ActiveTransport
    updated_at: float
    session_id: str | None = None
    aprs_endpoint: str | None = None


class PresenceRegistry:
    """Thread-safe, in-memory authoritative presence for this server process."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._users: dict[str, UserPresence] = {}

    def get(self, callsign: str) -> UserPresence | None:
        callsign = validate_callsign(callsign)
        with self._lock:
            return self._users.get(callsign)

    def set_websocket(self, callsign: str, session_id: str) -> UserPresence:
        callsign = validate_callsign(callsign)
        if not session_id:
            raise ValueError("session_id is required")
        value = UserPresence(
            callsign, ActiveTransport.WEBSOCKET, self._clock(), session_id=session_id
        )
        with self._lock:
            self._users[callsign] = value
        return value

    def set_aprs(self, callsign: str, endpoint: str) -> UserPresence:
        callsign = validate_callsign(callsign)
        if not endpoint:
            raise ValueError("APRS endpoint is required")
        value = UserPresence(
            callsign, ActiveTransport.APRS, self._clock(), aprs_endpoint=endpoint
        )
        with self._lock:
            self._users[callsign] = value
        return value

    def clear(self, callsign: str) -> bool:
        """Remove the current proactive route, regardless of its transport."""
        callsign = validate_callsign(callsign)
        with self._lock:
            return self._users.pop(callsign, None) is not None

    def clear_websocket(self, callsign: str, session_id: str) -> bool:
        """Clear only if ``session_id`` is still the authoritative session."""
        callsign = validate_callsign(callsign)
        with self._lock:
            current = self._users.get(callsign)
            if (
                current is None
                or current.active_transport is not ActiveTransport.WEBSOCKET
                or current.session_id != session_id
            ):
                return False
            del self._users[callsign]
            return True

    def clear_aprs(self, callsign: str, endpoint: str) -> bool:
        """Clear only if ``endpoint`` is still the authoritative APRS route."""
        callsign = validate_callsign(callsign)
        with self._lock:
            current = self._users.get(callsign)
            if (
                current is None
                or current.active_transport is not ActiveTransport.APRS
                or current.aprs_endpoint != endpoint
            ):
                return False
            del self._users[callsign]
            return True


WebSocketDelivery = Callable[[Message, str], bool]
APRSDelivery = Callable[[Message, str], bool]


class DeliveryRouter:
    """Select exactly the recipient's explicitly active transport."""

    def __init__(self, presence: PresenceRegistry | None = None) -> None:
        self.presence = presence or PresenceRegistry()
        self.websocket_delivery: WebSocketDelivery | None = None
        self.aprs_delivery: APRSDelivery | None = None

    def route(self, message: Message) -> ActiveTransport | None:
        current = self.presence.get(message.recipient)
        if current is None:
            return None
        if current.active_transport is ActiveTransport.WEBSOCKET:
            if self.websocket_delivery is not None and current.session_id is not None:
                self.websocket_delivery(message, current.session_id)
            return ActiveTransport.WEBSOCKET
        if self.aprs_delivery is not None and current.aprs_endpoint is not None:
            self.aprs_delivery(message, current.aprs_endpoint)
        return ActiveTransport.APRS

    def listener(self, message: Message) -> None:
        self.route(message)
