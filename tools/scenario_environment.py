"""Transport-neutral construction seam for development scenarios."""

from __future__ import annotations
from pathlib import Path
import asyncio
import threading
from typing import Protocol
from client_sim import DevelopmentClient, LocalCoreClient, TcpTransport
from openqsp.protocol import Bulletin, ProtocolObject, encode_frame
from openqsp.server import ServerCore
from openqsp.server.tcp import TCPServer
from openqsp.storage import BulletinStore, Database, MessageStore


class ScenarioClient(Protocol):
    """The only client behavior required by scenario flows."""

    def request(self, request: ProtocolObject) -> list[ProtocolObject]: ...


class ScenarioEnvironment(Protocol):
    """Node operations visible to transport-neutral scenarios."""

    def client(self, callsign: str) -> ScenarioClient: ...

    def restart_node(self) -> None: ...

    def seed_bulletin(self, bulletin: Bulletin) -> None: ...

    def close(self) -> None: ...


class LocalScenarioEnvironment:
    """Scenario environment backed by the production local Core and SQLite."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self._clients: dict[str, LocalCoreClient] = {}
        self._construct_node()

    def _construct_node(self) -> None:
        self._database = Database(self.database_path)
        self._database.initialize()
        self._messages = MessageStore(self._database)
        self._bulletins = BulletinStore(self._database)
        self._core = ServerCore(
            message_store=self._messages, bulletin_store=self._bulletins
        )

    def client(self, callsign: str) -> LocalCoreClient:
        client = self._clients.get(callsign)
        if client is None:
            client = self._clients[callsign] = LocalCoreClient(self._core, callsign)
        return client

    def restart_node(self) -> None:
        """Reconstruct the node and clients while retaining the database file."""
        self._clients.clear()
        self._construct_node()

    def seed_bulletin(self, bulletin: Bulletin) -> None:
        encode_frame(bulletin)
        outcome = self._bulletins.store_bulletin(
            created_at=bulletin.created_at,
            author=bulletin.author,
            title=bulletin.title,
            body=bulletin.body,
        )
        if outcome.result.name != "STORED":
            raise AssertionError(
                f"could not seed bulletin {bulletin.sequence}: {outcome}"
            )

    def close(self) -> None:
        self._clients.clear()


class RemoteScenarioEnvironment:
    """Development/test environment owning a real loopback TCP node.

    The asyncio server runs on a private background thread because scenario
    clients use the intentionally small synchronous transport API.  Bulletin
    setup retains direct access to the test-owned store; it is not exposed as
    a network operation.
    """

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self._clients: dict[str, DevelopmentClient] = {}
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._port = 0
        self._construct_node()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _construct_node(self) -> None:
        self._database = Database(self.database_path)
        self._database.initialize()
        self._messages = MessageStore(self._database)
        self._bulletins = BulletinStore(self._database)
        self._core = ServerCore(
            message_store=self._messages, bulletin_store=self._bulletins
        )
        self._server = TCPServer(self._core, host="127.0.0.1", port=self._port)
        asyncio.run_coroutine_threadsafe(self._server.start(), self._loop).result()
        self._port = self._server.sockets[0].getsockname()[1]

    def client(self, callsign: str) -> DevelopmentClient:
        client = self._clients.get(callsign)
        if client is None:
            client = self._clients[callsign] = DevelopmentClient(
                TcpTransport("127.0.0.1", self._port), callsign
            )
        return client

    def restart_node(self) -> None:
        """Stop the TCP listener and rebuild the full node on the same DB/port."""
        self._clients.clear()
        asyncio.run_coroutine_threadsafe(self._server.close(), self._loop).result()
        self._construct_node()

    def seed_bulletin(self, bulletin: Bulletin) -> None:
        encode_frame(bulletin)
        outcome = self._bulletins.store_bulletin(
            created_at=bulletin.created_at,
            author=bulletin.author,
            title=bulletin.title,
            body=bulletin.body,
        )
        if outcome.result.name != "STORED":
            raise AssertionError(
                f"could not seed bulletin {bulletin.sequence}: {outcome}"
            )

    def close(self) -> None:
        self._clients.clear()
        if self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._server.close(), self._loop).result()
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join()
            self._loop.close()
