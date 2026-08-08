"""Transport-neutral construction seam for development scenarios."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from client_sim import LocalCoreClient
from openqsp.protocol import Bulletin, ProtocolObject, encode_frame
from openqsp.server import ServerCore
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
            bulletin_id=bulletin.bulletin_id,
            created_at=bulletin.created_at,
            author=bulletin.author,
            title=bulletin.title,
            body=bulletin.body,
        )
        if outcome.result.name != "STORED":
            raise AssertionError(
                f"could not seed bulletin {bulletin.bulletin_id}: {outcome}"
            )

    def close(self) -> None:
        self._clients.clear()

