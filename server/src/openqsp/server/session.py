"""Application-level OpenQSP sessions, independent of any transport."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from time import monotonic
from typing import Protocol

from openqsp.protocol import (
    Error,
    ErrorCode,
    GetBulletin,
    GetNewBulletins,
    GetNewMessages,
    Operation,
    ProtocolObject,
    SendMessage,
    decode_frame,
    encode_frame,
    validate_callsign,
)
from openqsp.protocol.errors import (
    InvalidFieldError,
    PayloadLengthError,
    ProtocolDecodeError,
    UnsupportedVersionError,
)

SendBytes = Callable[[bytes], Awaitable[None]]


class CommandHandler(Protocol):
    """The command-dispatch seam implemented by the M5.2 dispatcher."""

    def handle(
        self, session: ApplicationSession, request: ProtocolObject
    ) -> Awaitable[None]: ...


class SessionState(Enum):
    CREATED = "created"
    ACTIVE = "active"
    CLOSED = "closed"


class SessionClosedError(RuntimeError):
    """An operation requiring a live application session was attempted."""


@dataclass(frozen=True)
class ActiveSession:
    """The registry-owned, current view of one active connection."""

    session_id: str
    callsign: str
    last_activity: float
    send: SendBytes


class SessionRegistry:
    """Tracks active sessions and supplies the server-delivery boundary.

    The registry owns activity timestamps and active membership.  An
    ``ApplicationSession`` only mirrors its own lifecycle state and delegates
    registration, refresh, removal, and server-initiated delivery here.
    """

    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._sessions: dict[str, ActiveSession] = {}
        self._lock = asyncio.Lock()

    async def register(self, session_id: str, callsign: str, send: SendBytes) -> None:
        async with self._lock:
            if session_id in self._sessions:
                raise ValueError(f"session already registered: {session_id}")
            self._sessions[session_id] = ActiveSession(
                session_id, callsign, self._clock(), send
            )

    async def refresh(self, session_id: str) -> None:
        async with self._lock:
            current = self._sessions.get(session_id)
            if current is None:
                raise SessionClosedError("session is not active")
            self._sessions[session_id] = ActiveSession(
                current.session_id, current.callsign, self._clock(), current.send
            )

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def get(self, session_id: str) -> ActiveSession | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def deliver(self, session_id: str, frame: bytes) -> bool:
        """Deliver bytes to an active session without holding registry locks."""

        async with self._lock:
            current = self._sessions.get(session_id)
        if current is None:
            return False
        await current.send(frame)
        async with self._lock:
            latest = self._sessions.get(session_id)
            if latest is current:
                self._sessions[session_id] = ActiveSession(
                    current.session_id,
                    current.callsign,
                    self._clock(),
                    current.send,
                )
        return True


class ApplicationSession:
    """One connected and identified OpenQSP client application session."""

    def __init__(
        self,
        *,
        callsign: str,
        session_id: str,
        registry: SessionRegistry,
        send: SendBytes,
        command_handler: CommandHandler,
    ) -> None:
        self.callsign = validate_callsign(callsign)
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id must be a non-empty string")
        if not callable(send):
            raise TypeError("send must be callable")
        if not callable(getattr(command_handler, "handle", None)):
            raise TypeError("command_handler must provide handle")
        self.session_id = session_id
        self._registry = registry
        self._send_bytes = send
        self._command_handler = command_handler
        self._state = SessionState.CREATED
        self._request_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()

    @property
    def state(self) -> SessionState:
        return self._state

    async def activate(self) -> None:
        """Register this created session as usable exactly once."""

        async with self._request_lock:
            if self._state is SessionState.CLOSED:
                raise SessionClosedError("closed sessions cannot be activated")
            if self._state is SessionState.ACTIVE:
                return
            await self._registry.register(
                self.session_id, self.callsign, self._send_from_registry
            )
            self._state = SessionState.ACTIVE

    async def receive(self, frame: bytes) -> None:
        """Decode and process one complete incoming OpenQSP Core frame."""

        async with self._request_lock:
            self._require_active()
            await self._registry.refresh(self.session_id)
            try:
                request = decode_frame(frame)
            except (ProtocolDecodeError, InvalidFieldError) as error:
                response = self._decode_error(frame, error)
                if response is not None:
                    await self.send(response)
                return

            if not isinstance(
                request,
                (SendMessage, GetNewMessages, GetNewBulletins, GetBulletin),
            ):
                await self.send(
                    Error(
                        self._operation(request),
                        ErrorCode.UNKNOWN_OPERATION,
                        "operation is not a client request",
                    )
                )
                return

            try:
                result = self._command_handler.handle(self, request)
                if not inspect.isawaitable(result):
                    raise TypeError("command handler must be asynchronous")
                await result
            except asyncio.CancelledError:
                raise
            except Exception:
                await self.send(
                    Error(
                        self._operation(request),
                        ErrorCode.INTERNAL_ERROR,
                        "request handling failed",
                    )
                )

    async def send(self, value: ProtocolObject) -> None:
        """Encode and emit one response/event through the injected boundary."""

        self._require_active()
        await self._send_serialized(encode_frame(value))
        await self._registry.refresh(self.session_id)

    async def close(self) -> None:
        """Wait for in-flight work, stop sends, and remove the session."""

        async with self._request_lock:
            async with self._send_lock:
                if self._state is SessionState.CLOSED:
                    return
                self._state = SessionState.CLOSED
                await self._registry.remove(self.session_id)

    async def _send_from_registry(self, frame: bytes) -> None:
        self._require_active()
        await self._send_serialized(frame)

    async def _send_serialized(self, frame: bytes) -> None:
        async with self._send_lock:
            self._require_active()
            await self._send_bytes(frame)

    def _require_active(self) -> None:
        if self._state is not SessionState.ACTIVE:
            raise SessionClosedError("session is not active")

    @staticmethod
    def _operation(request: ProtocolObject) -> Operation:
        operation_by_type = {
            SendMessage: Operation.SEND_MESSAGE,
            GetNewMessages: Operation.GET_NEW_MESSAGES,
            GetNewBulletins: Operation.GET_NEW_BULLETINS,
            GetBulletin: Operation.GET_BULLETIN,
        }
        return operation_by_type.get(type(request), Operation.ERROR)

    @staticmethod
    def _decode_error(
        frame: object, error: ProtocolDecodeError | InvalidFieldError
    ) -> Error | None:
        if not isinstance(frame, bytes) or len(frame) < 4:
            return None
        operation: Operation | int = 0
        if frame[0] == 1:
            try:
                operation = Operation(frame[1])
            except ValueError:
                pass
        if isinstance(error, UnsupportedVersionError):
            code, operation = ErrorCode.UNSUPPORTED_VERSION, 0
        elif isinstance(error, InvalidFieldError) and frame[2] == 0:
            code = ErrorCode.INVALID_FIELD
        elif isinstance(error, PayloadLengthError):
            code = ErrorCode.INVALID_FRAME
        else:
            code = ErrorCode.INVALID_FRAME
        return Error(operation, code, str(error)[:64])
