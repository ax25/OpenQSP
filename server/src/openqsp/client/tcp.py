"""Blocking reference client for authenticated OpenQSP TCP access."""

from __future__ import annotations

from collections.abc import Callable
import logging
import socket
import threading
import time

from openqsp.protocol import (
    Bulletin,
    Capabilities,
    BulletinHeader,
    End,
    Error,
    GetBulletin,
    GetCapabilities,
    GetNewBulletins,
    GetNewMessages,
    Message,
    Operation,
    ProtocolObject,
    SendMessage,
    Stored,
    decode_frame_with_flags,
    encode_frame,
    normalize_callsign,
)
from openqsp.protocol.constants import HEADER_SIZE, MAX_RETRIEVAL_MAX, UNSOLICITED_FLAG
from openqsp.protocol.errors import InvalidFieldError, ProtocolDecodeError
from openqsp.transport.tcp import (
    AUTH_PREFIX,
    HANDSHAKE_ERROR,
    HANDSHAKE_OK,
    HANDSHAKE_PREFIX,
    MAX_HANDSHAKE_SIZE,
)

logger = logging.getLogger(__name__)


class ClientError(Exception):
    """Base class for expected client failures."""


class AuthenticationError(ClientError):
    """Production authentication was rejected."""


class ConnectionClosedError(ClientError):
    """The peer disconnected or the client is not connected."""


class ProtocolResponseError(ClientError):
    """The server returned an OpenQSP ERROR response."""

    def __init__(self, response: Error) -> None:
        self.response = response
        super().__init__(f"{response.error_code.name}: {response.detail}")


class OpenQSPClient:
    """Thread-safe, blocking reference client with a background frame reader.

    Requests are serialized because version 0.1 has no request identifier.
    Unsolicited protocol objects received while no request is active are passed
    to ``event_handler`` and retained for :meth:`get_events`.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8023,
        *,
        timeout: float = 10.0,
        event_handler: Callable[[ProtocolObject], None] | None = None,
        allow_development_auth: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.event_handler = event_handler
        self.allow_development_auth = allow_development_auth
        self.callsign: str | None = None
        self._socket: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._condition = threading.Condition()
        self._request_lock = threading.Lock()
        self._pending_operation: Operation | None = None
        self._responses: list[ProtocolObject] = []
        self._events: list[ProtocolObject] = []
        self._failure: ClientError | None = None

    @property
    def connected(self) -> bool:
        return self._socket is not None

    @property
    def authenticated(self) -> bool:
        return self.connected and self.callsign is not None

    @property
    def endpoint(self) -> tuple[str, int]:
        return self.host, self.port

    def connect(self) -> None:
        """Open the TCP connection; call :meth:`authenticate` next."""
        if self.connected:
            raise ClientError("client is already connected")
        try:
            sock = socket.create_connection((self.host, self.port), self.timeout)
        except OSError as error:
            raise ClientError(
                f"cannot connect to {self.host}:{self.port}: {error}"
            ) from error
        sock.settimeout(None)
        self._socket = sock
        self._failure = None

    def authenticate(self, callsign: str, password: str | None = None) -> None:
        """Authenticate with a callsign and password over the bounded exchange."""
        if self._socket is None:
            raise ConnectionClosedError("client is not connected")
        if self.callsign is not None:
            raise ClientError("client is already authenticated")
        try:
            normalized = normalize_callsign(callsign)
            password_bytes = password.encode("utf-8") if password is not None else b""
            if password is not None and (
                not 1 <= len(password_bytes) <= 128
                or b"\x00" in password_bytes
                or b"\n" in password_bytes
            ):
                raise AuthenticationError("invalid credentials")
        except InvalidFieldError as error:
            raise AuthenticationError(str(error)) from error
        try:
            if password is None:
                if not self.allow_development_auth:
                    raise AuthenticationError("password is required")
                # Explicit compatibility path for test-only servers.
                authentication = HANDSHAKE_PREFIX + normalized.encode("ascii") + b"\n"
            else:
                authentication = (
                    AUTH_PREFIX
                    + normalized.encode("ascii")
                    + b" "
                    + password_bytes
                    + b"\n"
                )
            self._socket.sendall(authentication)
            response = self._read_line(MAX_HANDSHAKE_SIZE)
        except OSError as error:
            self.close()
            raise ConnectionClosedError(
                f"connection failed during authentication: {error}"
            ) from error
        if response != HANDSHAKE_OK:
            self.close()
            detail = (
                "invalid credentials"
                if response == HANDSHAKE_ERROR
                else "invalid authentication response"
            )
            raise AuthenticationError(detail)
        self.callsign = normalized
        self._reader = threading.Thread(
            target=self._reader_loop, name="openqsp-frame-reader", daemon=True
        )
        self._reader.start()

    def send_message(
        self,
        recipient: str,
        body: str,
        *,
        created_at: int | None = None,
    ) -> Stored:
        """Send one title-less private message and wait for durable storage."""
        timestamp = created_at if created_at is not None else int(time.time())
        responses = self.request(SendMessage(timestamp, recipient, body))
        if len(responses) != 1 or not isinstance(responses[0], Stored):
            raise ClientError("server returned an unexpected SEND_MESSAGE response")
        return responses[0]

    def get_messages(
        self, since: int = 0, maximum: int = MAX_RETRIEVAL_MAX
    ) -> tuple[list[Message], End]:
        responses = self.request(GetNewMessages(since, maximum))
        end = responses[-1] if responses else None
        if not isinstance(end, End) or any(
            not isinstance(item, Message) for item in responses[:-1]
        ):
            raise ClientError("server returned an unexpected GET_NEW_MESSAGES response")
        return list(responses[:-1]), end

    def get_bulletins(
        self, since: int = 0, maximum: int = MAX_RETRIEVAL_MAX
    ) -> tuple[list[BulletinHeader], End]:
        responses = self.request(GetNewBulletins(since, maximum))
        end = responses[-1] if responses else None
        if not isinstance(end, End) or any(
            not isinstance(item, BulletinHeader) for item in responses[:-1]
        ):
            raise ClientError(
                "server returned an unexpected GET_NEW_BULLETINS response"
            )
        return list(responses[:-1]), end

    def get_bulletin(self, sequence: int) -> Bulletin:
        responses = self.request(GetBulletin(sequence))
        if len(responses) != 1 or not isinstance(responses[0], Bulletin):
            raise ClientError("server returned an unexpected GET_BULLETIN response")
        return responses[0]

    def get_capabilities(self) -> Capabilities:
        responses = self.request(GetCapabilities())
        if len(responses) != 1 or not isinstance(responses[0], Capabilities):
            raise ClientError("server returned an unexpected GET_CAPABILITIES response")
        return responses[0]

    def request(self, request: ProtocolObject) -> list[ProtocolObject]:
        """Send one request and wait for its complete version 0.1 response."""
        operation = {
            SendMessage: Operation.SEND_MESSAGE,
            GetNewMessages: Operation.GET_NEW_MESSAGES,
            GetNewBulletins: Operation.GET_NEW_BULLETINS,
            GetBulletin: Operation.GET_BULLETIN,
            GetCapabilities: Operation.GET_CAPABILITIES,
        }.get(type(request))
        if operation is None:
            raise ClientError(f"{type(request).__name__} is not a client request")
        with self._request_lock:
            with self._condition:
                if not self.authenticated or self._failure is not None:
                    raise self._failure or ConnectionClosedError(
                        "client is not authenticated"
                    )
                self._pending_operation = operation
                self._responses = []
            try:
                assert self._socket is not None
                self._socket.sendall(encode_frame(request))
            except OSError as error:
                self._set_failure(ConnectionClosedError(f"send failed: {error}"))
            deadline = time.monotonic() + self.timeout
            with self._condition:
                while not self._complete():
                    if self._failure is not None:
                        raise self._failure
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._pending_operation = None
                        raise ClientError("timed out waiting for server response")
                    self._condition.wait(remaining)
                responses = self._responses
                self._responses = []
                self._pending_operation = None
            error = next((item for item in responses if isinstance(item, Error)), None)
            if error is not None:
                raise ProtocolResponseError(error)
            return responses

    def get_events(self) -> list[ProtocolObject]:
        """Remove and return unsolicited objects accumulated so far."""
        with self._condition:
            events, self._events = self._events, []
            return events

    def close(self) -> None:
        """Idempotently close the socket and stop the reader."""
        sock, self._socket = self._socket, None
        self.callsign = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=1)
        self._reader = None
        with self._condition:
            self._condition.notify_all()

    def __enter__(self) -> OpenQSPClient:
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _read_line(self, limit: int) -> bytes:
        assert self._socket is not None
        result = bytearray()
        while len(result) < limit:
            byte = self._socket.recv(1)
            if not byte:
                break
            result += byte
            if byte == b"\n":
                break
        return bytes(result)

    def _read_exactly(self, size: int) -> bytes:
        assert self._socket is not None
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self._socket.recv(size - len(chunks))
            if not chunk:
                raise ConnectionClosedError("server disconnected")
            chunks += chunk
        return bytes(chunks)

    def _reader_loop(self) -> None:
        try:
            while self._socket is not None:
                header = self._read_exactly(HEADER_SIZE)
                obj, flags = decode_frame_with_flags(
                    header + self._read_exactly(header[3])
                )
                handler = None
                with self._condition:
                    if flags & UNSOLICITED_FLAG:
                        self._events.append(obj)
                        handler = self.event_handler
                    elif self._pending_operation is None:
                        raise ClientError(
                            "server sent an unmarked frame with no active request"
                        )
                    else:
                        self._responses.append(obj)
                    self._condition.notify_all()
                if handler is not None:
                    try:
                        handler(obj)
                    except Exception:
                        # A UI callback must never kill transport processing,
                        # but callback defects must remain visible to callers.
                        logger.exception("event handler failed for unsolicited frame")
        except (OSError, ConnectionClosedError) as error:
            if self._socket is not None:
                self._set_failure(ConnectionClosedError(str(error)))
        except (ProtocolDecodeError, InvalidFieldError, ValueError) as error:
            self._set_failure(ClientError(f"invalid server frame: {error}"))
        except ClientError as error:
            self._set_failure(error)

    def _complete(self) -> bool:
        if not self._responses:
            return False
        last = self._responses[-1]
        if isinstance(last, Error):
            return True
        if self._pending_operation == Operation.SEND_MESSAGE:
            return isinstance(last, Stored)
        if self._pending_operation in (
            Operation.GET_NEW_MESSAGES,
            Operation.GET_NEW_BULLETINS,
        ):
            return (
                isinstance(last, End)
                and last.request_operation == self._pending_operation
            )
        if self._pending_operation == Operation.GET_BULLETIN:
            return isinstance(last, Bulletin)
        if self._pending_operation == Operation.GET_CAPABILITIES:
            return isinstance(last, Capabilities)
        return False

    def _set_failure(self, failure: ClientError) -> None:
        sock, self._socket = self._socket, None
        self.callsign = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        with self._condition:
            self._failure = failure
            self._condition.notify_all()
