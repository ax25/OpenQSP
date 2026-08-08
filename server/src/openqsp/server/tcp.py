"""Minimal development TCP transport for OpenQSP Core frames.

The connection starts with the ASCII line ``CALLSIGN <callsign>\n``.  A valid
line receives ``OK\n``; an invalid line receives ``ERROR\n`` and is closed.
This is deliberately development-only identification, not authentication.
Afterwards, unmodified Core frames are exchanged using their four-byte header
and its one-byte payload length.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from openqsp.protocol import validate_callsign
from openqsp.protocol.constants import HEADER_SIZE, MAX_FRAME_SIZE
from openqsp.protocol.errors import InvalidFieldError
from openqsp.storage import BulletinStore, Database, MessageStore

from .core import ServerCore

MAX_HANDSHAKE_SIZE = 32
HANDSHAKE_PREFIX = b"CALLSIGN "
HANDSHAKE_OK = b"OK\n"
HANDSHAKE_ERROR = b"ERROR\n"


class TCPServer:
    """Async TCP adapter around one injected :class:`ServerCore`."""

    def __init__(
        self,
        server_core: ServerCore,
        *,
        host: str = "127.0.0.1",
        port: int = 8023,
    ) -> None:
        self.server_core = server_core
        self.host = host
        self.port = port
        self._server: asyncio.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self._client_tasks: set[asyncio.Task[None]] = set()

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
            limit=MAX_HANDSHAKE_SIZE + 1,
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
            await asyncio.gather(
                *(writer.wait_closed() for writer in writers),
                return_exceptions=True,
            )
        tasks = tuple(
            task for task in self._client_tasks if task is not asyncio.current_task()
        )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def __aenter__(self) -> TCPServer:
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

                for response in self.server_core.handle_frame(
                    callsign, header + payload
                ):
                    writer.write(response)
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            return
        finally:
            self._writers.discard(writer)
            if task is not None:
                self._client_tasks.discard(task)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    @staticmethod
    async def _authenticate(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> str | None:
        try:
            line = await reader.readline()
        except (ValueError, asyncio.LimitOverrunError):
            line = b""
        callsign: str | None = None
        if line.endswith(b"\n") and len(line) <= MAX_HANDSHAKE_SIZE:
            value = line.removesuffix(b"\n").removesuffix(b"\r")
            if value.startswith(HANDSHAKE_PREFIX):
                try:
                    candidate = value[len(HANDSHAKE_PREFIX) :].decode("ascii")
                    callsign = validate_callsign(candidate)
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
    return parser


async def _run(host: str, port: int, database_path: Path) -> None:
    database = Database(database_path)
    database.initialize()
    core = ServerCore(
        message_store=MessageStore(database),
        bulletin_store=BulletinStore(database),
    )
    server = TCPServer(core, host=host, port=port)
    async with server:
        addresses = ", ".join(str(socket.getsockname()) for socket in server.sockets)
        print(f"OpenQSP development TCP server listening on {addresses}")
        print(f"SQLite database: {database_path}")
        print("Authentication: development-only CALLSIGN handshake (NOT production)")
        await server.serve_forever()


def main(argv: Sequence[str] | None = None) -> None:
    """Run a development node from the command line."""
    args = _parser().parse_args(argv)
    try:
        asyncio.run(_run(args.host, args.port, args.database))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
