import asyncio
from pathlib import Path

from openqsp.server.app import OpenQSPServer
from openqsp.server.config import ServerConfig


class FakeTCP:
    def __init__(self, core, **kwargs):
        self.core, self.kwargs = core, kwargs
        self.started = self.closed = False

    async def start(self):
        self.started = True

    async def close(self):
        self.closed = True


class FakeAdapter:
    def __init__(self, core, **kwargs):
        self.core, self.kwargs = core, kwargs
        self.closed = False

    def close(self):
        self.closed = True


class FakeAPRSClient:
    def __init__(self, adapter, config):
        self.adapter, self.config = adapter, config
        self.stopped = False

    async def run(self):
        while not self.stopped:
            await asyncio.sleep(3600)

    def stop(self):
        self.stopped = True


def test_combined_runtime_shares_core_and_closes(tmp_path: Path) -> None:
    async def scenario():
        config = ServerConfig(
            database=tmp_path / "shared.db",
            tcp_enabled=True,
            aprs_enabled=True,
            aprs_callsign="NODE",
            aprs_passcode="credential",
        )
        app = OpenQSPServer(
            config,
            tcp_factory=FakeTCP,
            aprs_adapter_factory=FakeAdapter,
            aprs_client_factory=FakeAPRSClient,
        )
        await app.start()
        assert app.tcp.started
        assert app.tcp.core is app.core is app.aprs_adapter.core
        assert app.aprs_client.config.callsign == "NODE"
        assert app.aprs_client.config.filter == "g/NODE"
        await app.close()
        assert app.tcp.closed and app.aprs_adapter.closed
        assert app.aprs_client.stopped
        assert app._aprs_task is None

    asyncio.run(scenario())


def test_tcp_only_and_aprs_only_startup(tmp_path: Path) -> None:
    async def scenario():
        tcp = OpenQSPServer(
            ServerConfig(database=tmp_path / "tcp.db"), tcp_factory=FakeTCP
        )
        await tcp.start()
        assert tcp.tcp is not None and tcp.aprs_client is None
        await tcp.close()
        aprs = OpenQSPServer(
            ServerConfig(
                database=tmp_path / "aprs.db",
                tcp_enabled=False,
                aprs_enabled=True,
                aprs_callsign="NODE",
                aprs_passcode="credential",
            ),
            aprs_adapter_factory=FakeAdapter,
            aprs_client_factory=FakeAPRSClient,
        )
        await aprs.start()
        assert aprs.tcp is None and aprs.aprs_client is not None
        await aprs.close()

    asyncio.run(scenario())
