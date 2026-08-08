#!/usr/bin/env python3
"""Emulate one OpenQSP user against a local Core or development TCP node."""

from __future__ import annotations

import argparse
from pathlib import Path
import socket
import sys
from typing import Protocol

# Make the production package importable from an uninstalled checkout.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVER_SRC = REPOSITORY_ROOT / "server" / "src"
if str(SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(SERVER_SRC))

from openqsp.protocol import (  # noqa: E402
    Bulletin,
    BulletinHeader,
    End,
    Error,
    GetBulletin,
    GetNewBulletins,
    GetNewMessages,
    Message,
    Operation,
    ProtocolObject,
    SendMessage,
    Stored,
    decode_frame,
    encode_frame,
)
from openqsp.protocol.errors import ProtocolError  # noqa: E402
from openqsp.protocol.constants import HEADER_SIZE, MAX_FRAME_SIZE  # noqa: E402
from openqsp.server import ServerCore  # noqa: E402
from openqsp.storage import BulletinStore, Database, MessageStore  # noqa: E402


class ClientTransport(Protocol):
    """Move one encoded OpenQSP exchange to a node and back."""

    def exchange(self, callsign: str, request_frame: bytes) -> list[bytes]:
        """Return the encoded response frames for ``request_frame``."""
        ...


class LocalCoreTransport:
    """Deliver encoded frames directly to a local ``ServerCore``."""

    def __init__(self, core: ServerCore) -> None:
        self._core = core

    def exchange(self, callsign: str, request_frame: bytes) -> list[bytes]:
        """Forward an exchange without interpreting any protocol frames."""
        return self._core.handle_frame(callsign, request_frame)


class TransportError(RuntimeError):
    """Base class for failures moving frames to a remote node."""


class ConnectionFailed(TransportError):
    """A TCP connection could not be established or was lost."""


class DevelopmentHandshakeError(TransportError):
    """The development-only callsign handshake was rejected or malformed."""


class TruncatedResponseError(TransportError):
    """The peer closed part way through a response frame."""


class TcpTransport:
    """Exchange frames with the development TCP server.

    A fresh connection is deliberately used for every exchange.  Response
    boundaries are found from the request/response operation contract rather
    than connection closure, so this remains compatible with the server's
    reusable connections while avoiding a client-side session manager.
    """

    _TERMINATORS = {
        Operation.SEND_MESSAGE: {Operation.STORED, Operation.ERROR},
        Operation.GET_NEW_MESSAGES: {Operation.END, Operation.ERROR},
        Operation.GET_NEW_BULLETINS: {Operation.END, Operation.ERROR},
        Operation.GET_BULLETIN: {Operation.BULLETIN, Operation.ERROR},
    }

    def __init__(self, host: str, port: int, *, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def exchange(self, callsign: str, request_frame: bytes) -> list[bytes]:
        try:
            request_operation = Operation(request_frame[1])
            terminators = self._TERMINATORS[request_operation]
        except (IndexError, ValueError, KeyError) as exc:
            raise ValueError("request is not a supported client operation") from exc

        try:
            connection = socket.create_connection(
                (self.host, self.port), timeout=self.timeout
            )
        except OSError as exc:
            raise ConnectionFailed(
                f"could not connect to {self.host}:{self.port}: {exc}"
            ) from exc

        with connection:
            connection.settimeout(self.timeout)
            try:
                connection.sendall(f"CALLSIGN {callsign}\n".encode("ascii"))
                handshake = self._receive_line(connection, 32)
                if handshake != b"OK\n":
                    raise DevelopmentHandshakeError(
                        f"development callsign handshake returned {handshake!r}"
                    )
                connection.sendall(request_frame)

                frames: list[bytes] = []
                while True:
                    frame = self._receive_frame(connection)
                    frames.append(frame)
                    try:
                        response_operation = Operation(frame[1])
                    except ValueError:
                        # The production decoder will report the protocol error.
                        return frames
                    if response_operation in terminators:
                        return frames
            except TransportError:
                raise
            except (OSError, UnicodeEncodeError) as exc:
                raise ConnectionFailed(f"TCP exchange failed: {exc}") from exc

    @staticmethod
    def _receive_line(connection: socket.socket, maximum: int) -> bytes:
        line = bytearray()
        while len(line) < maximum:
            chunk = connection.recv(1)
            if not chunk:
                raise ConnectionFailed("server closed during development handshake")
            line.extend(chunk)
            if chunk == b"\n":
                return bytes(line)
        raise DevelopmentHandshakeError("development handshake response is too long")

    @classmethod
    def _receive_frame(cls, connection: socket.socket) -> bytes:
        header = cls._receive_exact(connection, HEADER_SIZE, header=True)
        frame_size = HEADER_SIZE + header[3]
        if frame_size > MAX_FRAME_SIZE:  # Defensive if the header grows later.
            raise TransportError(f"response frame exceeds {MAX_FRAME_SIZE} bytes")
        return header + cls._receive_exact(
            connection, frame_size - HEADER_SIZE, header=False
        )

    @staticmethod
    def _receive_exact(
        connection: socket.socket, size: int, *, header: bool
    ) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = connection.recv(size - len(data))
            if not chunk:
                if data or not header:
                    raise TruncatedResponseError("server closed during response frame")
                raise ConnectionFailed("server closed before sending a response")
            data.extend(chunk)
        return bytes(data)


class DevelopmentClient:
    """One authenticated user communicating through a client transport.

    This class owns request encoding and response decoding.  Its transport is
    responsible only for moving the resulting encoded frames.
    """

    def __init__(self, transport: ClientTransport, callsign: str) -> None:
        self._transport = transport
        self.callsign = callsign

    def request(self, request: ProtocolObject) -> list[ProtocolObject]:
        """Send one production-encoded request as this authenticated user."""
        request_frame = encode_frame(request)
        response_frames = self._transport.exchange(self.callsign, request_frame)
        return decode_responses(response_frames)


class LocalCoreClient(DevelopmentClient):
    """Backwards-compatible client convenience wrapper for a local core."""

    def __init__(self, core: ServerCore, callsign: str) -> None:
        super().__init__(LocalCoreTransport(core), callsign)


def parse_integer(value: str) -> int:
    """Parse decimal and 0x-prefixed integer arguments."""
    try:
        return int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer: {value!r}") from exc


def decode_responses(frames: list[bytes]) -> list[ProtocolObject]:
    """Decode server output solely through the production codec."""
    return [decode_frame(frame) for frame in frames]


def completed_cursor(
    responses: list[ProtocolObject], request_operation: Operation
) -> int | None:
    """Return a cursor only from the terminating END of a complete response.

    A caller processing a partial frame list therefore cannot accidentally
    advance from the sequence carried by an item frame.
    """
    if not responses or not isinstance(responses[-1], End):
        return None
    end = responses[-1]
    if end.request_operation != request_operation:
        return None
    return end.next_since


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--db", type=Path, help="local mode: persistent SQLite DB")
    mode.add_argument("--tcp-host", help="remote mode: development TCP node host")
    parser.add_argument("--tcp-port", type=int, default=8023, help="remote TCP port")
    parser.add_argument(
        "--callsign",
        required=True,
        help="authenticated test callsign (passed unchanged to ServerCore)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    send = commands.add_parser("send-message", help="submit a private message")
    send.add_argument("--to", required=True, dest="recipient")
    send.add_argument("--timestamp", required=True, type=parse_integer)
    send.add_argument("--body", required=True)

    for name in ("get-new-messages", "get-new-bulletins"):
        retrieval = commands.add_parser(name)
        retrieval.add_argument("--since", required=True, type=parse_integer)
        retrieval.add_argument("--max", required=True, type=parse_integer)

    bulletin = commands.add_parser("get-bulletin")
    bulletin.add_argument("--sequence", required=True, type=parse_integer)

    seed = commands.add_parser(
        "seed-bulletin",
        help="development-only node setup (not an OpenQSP client operation)",
    )
    seed.add_argument("--timestamp", required=True, type=parse_integer)
    seed.add_argument("--title", required=True)
    seed.add_argument("--body", required=True)
    return parser


def _request(args: argparse.Namespace) -> ProtocolObject:
    if args.command == "send-message":
        return SendMessage(args.timestamp, args.recipient, args.body)
    if args.command == "get-new-messages":
        return GetNewMessages(args.since, args.max)
    if args.command == "get-new-bulletins":
        return GetNewBulletins(args.since, args.max)
    if args.command == "get-bulletin":
        return GetBulletin(args.sequence)
    raise ValueError(f"not a client operation: {args.command}")


def _print_response(response: ProtocolObject) -> None:
    if isinstance(response, Stored):
        print("STORED")
    elif isinstance(response, Message):
        print("MESSAGE")
        print(f"  sequence: {response.sequence}")
        print(f"  created_at: {response.created_at}")
        print(f"  author: {response.author}")
        print(f"  recipient: {response.recipient}")
        print(f"  body: {response.body}")
    elif isinstance(response, BulletinHeader):
        print("BULLETIN_HEADER")
        print(f"  sequence: {response.sequence}")
        print(f"  created_at: {response.created_at}")
        print(f"  author: {response.author}")
        print(f"  title: {response.title}")
    elif isinstance(response, Bulletin):
        print("BULLETIN")
        print(f"  sequence: {response.sequence}")
        print(f"  created_at: {response.created_at}")
        print(f"  author: {response.author}")
        print(f"  title: {response.title}")
        print(f"  body: {response.body}")
    elif isinstance(response, End):
        print("END")
        print(f"  returned: {response.returned_count}")
        print(f"  next_since: {response.next_since}")
        print(f"  has_more: {str(response.has_more).lower()}")
    elif isinstance(response, Error):
        print("ERROR")
        print(f"  operation: {getattr(response.request_operation, 'name', 0)}")
        print(f"  code: {response.error_code.name}")
        print(f"  detail: {response.detail}")
    else:  # pragma: no cover - all v0.1 response models are handled above.
        raise TypeError(f"unexpected response: {type(response).__name__}")
    print()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        if args.command == "seed-bulletin":
            if args.db is None:
                raise ValueError("seed-bulletin is available only in local --db mode")
            database = Database(args.db)
            database.initialize()
            bulletin_store = BulletinStore(database)
            # This is node/test setup, deliberately separated from client
            # operations. Encoding validates fields before direct store setup.
            bulletin = Bulletin(
                1,
                args.timestamp,
                args.callsign,
                args.title,
                args.body,
            )
            encode_frame(bulletin)
            sequence = bulletin_store.store_bulletin(
                created_at=bulletin.created_at,
                author=bulletin.author,
                title=bulletin.title,
                body=bulletin.body,
            )
            print("DEVELOPMENT SEED")
            print(f"  sequence: {sequence}")
            return 0

        if args.tcp_host is not None:
            print(
                f"REMOTE DEVELOPMENT TCP {args.tcp_host}:{args.tcp_port}",
                file=sys.stderr,
            )
            client = DevelopmentClient(
                TcpTransport(args.tcp_host, args.tcp_port), args.callsign
            )
        else:
            database = Database(args.db)
            database.initialize()
            bulletin_store = BulletinStore(database)
            core = ServerCore(
                message_store=MessageStore(database), bulletin_store=bulletin_store
            )
            client = LocalCoreClient(core, args.callsign)
        responses = client.request(_request(args))
    except (ProtocolError, TransportError, TypeError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    for response in responses:
        _print_response(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
