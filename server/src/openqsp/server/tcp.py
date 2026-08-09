"""Authenticated TCP adapter for OpenQSP Core frames.

The connection starts with ``AUTH <callsign> <password>\n``. Authentication
failures all receive the same ``ERROR\n`` response and close. An explicitly
enabled test-only mode accepts the historical ``CALLSIGN`` line.
Afterwards, unmodified Core frames are exchanged using their four-byte header
and its one-byte payload length.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Self

from openqsp.protocol import encode_frame, validate_callsign
from openqsp.protocol.constants import HEADER_SIZE, MAX_FRAME_SIZE
from openqsp.protocol.errors import InvalidFieldError
from openqsp.storage import (
    AccountStore,
    BulletinStore,
    Database,
    InvalidCredentialsError,
    MessageStore,
)
from openqsp.transport.tcp import (
    AUTH_PREFIX,
    HANDSHAKE_ERROR,
    HANDSHAKE_OK,
    HANDSHAKE_PREFIX,
    MAX_HANDSHAKE_SIZE,
)

from .core import ServerCore
from .sessions import SessionRegistry


class TCPServer:
    """Async TCP adapter around one injected :class:`ServerCore`."""

    def __init__(
        self,
        server_core: ServerCore,
        *,
        host: str = "127.0.0.1",
        port: int = 8023,
        account_store: AccountStore | None = None,
        sessions: SessionRegistry | None = None,
        allow_development_auth: bool = False,
    ) -> None:
        self.server_core = server_core
        self.host = host
        self.port = port
        self.account_store = account_store
        self.sessions = sessions or SessionRegistry()
        self.allow_development_auth = allow_development_auth
        self._server: asyncio.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self._client_tasks: set[asyncio.Task[None]] = set()
        if hasattr(self.server_core, "add_message_listener"):
            self.server_core.add_message_listener(self.sessions.deliver_message)

    @property
    def sockets(self) -> tuple[object, ...]:
        """Listening sockets, available after :meth:`start`."""
        if self._server is None or self._server.sockets is None:
            return ()
        return tuple(self._server.sockets)

    async def start(self) -> None:
        """Start accepting connections."""
        if self._server is not None:
            raise RuntimeError("TCP server is already started")
        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
            # StreamReader uses this limit to pause its transport while a
            # readexactly() is pending too.  It must therefore accommodate a
            # complete maximum-size Core frame, not just the handshake line.
            limit=MAX_FRAME_SIZE,
        )

    async def serve_forever(self) -> None:
        """Serve until cancelled; :meth:`start` must be called first."""
        if self._server is None:
            raise RuntimeError("TCP server is not started")
        await self._server.serve_forever()

    async def close(self) -> None:
        """Stop accepting clients and close all current connections."""
        server, self._server = self._server, None
        if server is not None:
            server.close()
            await server.wait_closed()

        writers = tuple(self._writers)
        for writer in writers:
            writer.close()
        if writers:
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *(writer.wait_closed() for writer in writers),
                        return_exceptions=True,
                    ),
                    timeout=1,
                )
            except TimeoutError:
                for writer in writers:
                    writer.transport.abort()
        tasks = tuple(
            task for task in self._client_tasks if task is not asyncio.current_task()
        )
        if tasks:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if hasattr(self.server_core, "remove_message_listener"):
            self.server_core.remove_message_listener(self.sessions.deliver_message)

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._client_tasks.add(task)
        self._writers.add(writer)
        try:
            callsign = await self._authenticate(reader, writer)
            if callsign is None:
                return

            def deliver(obj: object) -> bool:
                if writer.is_closing():
                    return False
                writer.write(encode_frame(obj, unsolicited=True))
                return True

            session = self.sessions.create(callsign, deliver)
            while True:
                try:
                    header = await reader.readexactly(HEADER_SIZE)
                except asyncio.IncompleteReadError:
                    return
                payload_length = header[3]
                frame_length = HEADER_SIZE + payload_length
                if frame_length > MAX_FRAME_SIZE:
                    return
                try:
                    payload = await reader.readexactly(payload_length)
                except asyncio.IncompleteReadError:
                    return

                session.touch()
                for response in self.server_core.handle_frame(
                    session.callsign, header + payload
                ):
                    writer.write(response)
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            return
        finally:
            if "session" in locals():
                self.sessions.close(session)
            self._writers.discard(writer)
            if task is not None:
                self._client_tasks.discard(task)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    async def _authenticate(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> str | None:
        try:
            line = await reader.readline()
        except (ValueError, asyncio.LimitOverrunError):
            line = b""
        callsign: str | None = None
        if line.endswith(b"\n") and len(line) <= MAX_HANDSHAKE_SIZE:
            value = line.removesuffix(b"\n").removesuffix(b"\r")
            if value.startswith(AUTH_PREFIX) and self.account_store is not None:
                parts = value[len(AUTH_PREFIX) :].split(b" ", 1)
                try:
                    if len(parts) != 2:
                        raise ValueError
                    callsign = self.account_store.authenticate(
                        parts[0].decode("ascii"), parts[1].decode("utf-8")
                    )
                except (UnicodeDecodeError, InvalidCredentialsError, ValueError):
                    pass
            elif self.allow_development_auth and value.startswith(HANDSHAKE_PREFIX):
                try:
                    callsign = validate_callsign(
                        value[len(HANDSHAKE_PREFIX) :].decode("ascii")
                    )
                except (UnicodeDecodeError, InvalidFieldError):
                    pass
        writer.write(HANDSHAKE_OK if callsign is not None else HANDSHAKE_ERROR)
        try:
            await writer.drain()
        except ConnectionError:
            return None
        return callsign


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8023)
    parser.add_argument("--database", type=Path, default=Path("openqsp.db"))
    parser.add_argument(
        "--create-account",
        nargs=2,
        metavar=("CALLSIGN", "PASSWORD"),
        help="provision an account and exit",
    )
    return parser


async def _run(host: str, port: int, database_path: Path) -> None:
    database = Database(database_path)
    database.initialize()
    core = ServerCore(
        message_store=MessageStore(database),
        bulletin_store=BulletinStore(database),
    )
    server = TCPServer(core, host=host, port=port, account_store=AccountStore(database))
    async with server:
        addresses = ", ".join(str(socket.getsockname()) for socket in server.sockets)
        print(f"OpenQSP TCP server listening on {addresses}")
        print(f"SQLite database: {database_path}")
        print("Authentication: callsign + password")
        await server.serve_forever()


def main(argv: Sequence[str] | None = None) -> None:
    """Run a development node from the command line."""
    args = _parser().parse_args(argv)
    if args.create_account:
        database = Database(args.database)
        database.initialize()
        callsign = AccountStore(database).create_account(*args.create_account)
        print(f"Created account {callsign}")
        return
    try:
        asyncio.run(_run(args.host, args.port, args.database))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
