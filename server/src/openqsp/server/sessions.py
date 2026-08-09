"""Transport-independent authenticated runtime sessions and presence."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from openqsp.protocol import Message, ProtocolObject, validate_callsign

OutboundDelivery = Callable[[ProtocolObject], bool]


@dataclass
class AuthenticatedSession:
    """One active runtime binding for a durable OpenQSP account."""

    callsign: str
    deliver: OutboundDelivery
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    active: bool = True
    last_activity: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        validate_callsign(self.callsign)

    def touch(self) -> None:
        if self.active:
            self.last_activity = time.monotonic()

    def close(self) -> None:
        self.active = False


class SessionRegistry:
    """Thread-safe presence registry; never holds its lock during delivery."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, AuthenticatedSession] = {}

    def create(self, callsign: str, deliver: OutboundDelivery) -> AuthenticatedSession:
        session = AuthenticatedSession(callsign, deliver)
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def close(self, session: AuthenticatedSession) -> None:
        with self._lock:
            self._sessions.pop(session.session_id, None)
            session.close()

    def active_for(self, callsign: str) -> tuple[AuthenticatedSession, ...]:
        with self._lock:
            return tuple(
                session
                for session in self._sessions.values()
                if session.active and session.callsign == callsign
            )

    def deliver_message(self, message: Message) -> int:
        """Best-effort push to every active session; durable mail is untouched."""
        delivered = 0
        for session in self.active_for(message.recipient):
            try:
                if session.deliver(message):
                    delivered += 1
                    session.touch()
            except (ConnectionError, OSError):
                # The owning adapter performs deterministic disconnect cleanup.
                continue
        return delivered

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(session.active for session in self._sessions.values())
