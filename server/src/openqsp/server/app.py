"""Production OpenQSP runtime sharing one Core across enabled transports."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from collections.abc import Callable, Sequence
from pathlib import Path

from openqsp.storage import AccountStore, BulletinStore, Database, MessageStore
from openqsp.transport.aprs import APRSAdapter
from openqsp.transport.aprs.aprsis import APRSISClient, APRSISConfig

from .config import ConfigurationError, ServerConfig, load_dotenv
from .core import ServerCore
from .tcp import TCPServer

logger = logging.getLogger(__name__)


class OpenQSPServer:
    """Own transport lifecycles and the node's single persistent Core."""

    def __init__(
        self,
        config: ServerConfig,
        *,
        tcp_factory: Callable[..., TCPServer] = TCPServer,
        aprs_adapter_factory: Callable[..., APRSAdapter] = APRSAdapter,
        aprs_client_factory: Callable[..., APRSISClient] = APRSISClient,
    ) -> None:
        config.validate()
        self.config = config
        self.database = Database(config.database)
        self.database.initialize()
        self.message_store = MessageStore(self.database)
        self.bulletin_store = BulletinStore(self.database)
        self.account_store = AccountStore(self.database)
        self.core = ServerCore(
            message_store=self.message_store, bulletin_store=self.bulletin_store
        )
        self.tcp: TCPServer | None = None
        self.aprs_adapter: APRSAdapter | None = None
        self.aprs_client: APRSISClient | None = None
        self._aprs_task: asyncio.Task[None] | None = None
        self._api_server: object | None = None
        self._api_task: asyncio.Task[None] | None = None
        self._closed = asyncio.Event()
        self._close_started = False
        self._tcp_factory = tcp_factory
        self._adapter_factory = aprs_adapter_factory
        self._client_factory = aprs_client_factory

    async def start(self) -> None:
        logger.info("OpenQSP server starting")
        logger.info("Database: %s", self.config.database)
        if self.config.tcp_enabled:
            self.tcp = self._tcp_factory(
                self.core,
                host=self.config.tcp_host,
                port=self.config.tcp_port,
                account_store=self.account_store,
            )
            await self.tcp.start()
            logger.info(
                "TCP: listening on %s:%s", self.config.tcp_host, self.config.tcp_port
            )
        if self.config.aprs_enabled:
            assert self.config.aprs_callsign and self.config.aprs_passcode
            self.aprs_adapter = self._adapter_factory(
                self.core, service_callsign=self.config.aprs_callsign
            )
            aprs_config = APRSISConfig(
                callsign=self.config.aprs_callsign,
                passcode=self.config.aprs_passcode,
                host=self.config.aprs_host,
                port=self.config.aprs_port,
                filter=self.config.effective_aprs_filter,
            )
            self.aprs_client = self._client_factory(self.aprs_adapter, aprs_config)
            self._aprs_task = asyncio.create_task(
                self.aprs_client.run(), name="aprs-is"
            )
        if self.config.api_enabled:
            import uvicorn

            from openqsp.api import EventHub, create_api

            assert self.config.api_token_secret
            hub = EventHub()
            self.core.add_message_listener(hub.listener)
            api = create_api(
                accounts=self.account_store,
                messages=self.message_store,
                secret=self.config.api_token_secret,
                token_lifetime=self.config.api_token_lifetime,
                cors_origins=self.config.api_cors_origins,
                hub=hub,
            )
            self._api_server = uvicorn.Server(
                uvicorn.Config(
                    api,
                    host=self.config.api_host,
                    port=self.config.api_port,
                    log_level="info",
                )
            )
            self._api_task = asyncio.create_task(
                self._api_server.serve(), name="internet-api"
            )
            logger.info(
                "API: listening on %s:%s", self.config.api_host, self.config.api_port
            )
        logger.info("OpenQSP server ready")

    async def serve_forever(self) -> None:
        await self._closed.wait()

    async def close(self) -> None:
        if self._close_started:
            return
        self._close_started = True
        if self.aprs_client is not None:
            self.aprs_client.stop()
        if self._aprs_task is not None:
            self._aprs_task.cancel()
            await asyncio.gather(self._aprs_task, return_exceptions=True)
            self._aprs_task = None
        if self._api_server is not None:
            setattr(self._api_server, "should_exit", True)
        if self._api_task is not None:
            await self._api_task
            self._api_task = None
        if self.aprs_adapter is not None:
            self.aprs_adapter.close()
        if self.tcp is not None:
            await self.tcp.close()
        self._closed.set()
        logger.info("OpenQSP server shut down cleanly")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an OpenQSP server node")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--host", help="TCP listen host")
    parser.add_argument("--port", type=int, help="TCP listen port")
    parser.add_argument("--create-account", nargs=2, metavar=("CALLSIGN", "PASSWORD"))
    return parser


async def _run(config: ServerConfig) -> None:
    app = OpenQSPServer(config)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, app._closed.set)
        except NotImplementedError:  # pragma: no cover - Windows event loops
            pass
    try:
        await app.start()
        await app.serve_forever()
    finally:
        await app.close()


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        load_dotenv()
        args = _parser().parse_args(argv)
        config = ServerConfig.from_environment().with_overrides(
            database=args.database, tcp_host=args.host, tcp_port=args.port
        )
        if args.create_account:
            database = Database(config.database)
            database.initialize()
            callsign = AccountStore(database).create_account(*args.create_account)
            print(f"Created account {callsign}")
            return
        asyncio.run(_run(config))
    except ConfigurationError as error:
        raise SystemExit(f"configuration error: {error}") from error
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
