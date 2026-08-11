"""APRS-IS line codec and reconnecting asynchronous service connection."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from .adapter import SERVICE_CALLSIGN, APRSAdapter, OutboundPacket

logger = logging.getLogger(__name__)

DEFAULT_HOST = "rotate.aprs2.net"
DEFAULT_PORT = 14580
_PACKET_RE = re.compile(r"([^>]+)>[^:]+::(.{9}):(.*)")
_LOGRESP_RE = re.compile(
    r"# logresp ([^ ]+) (verified|unverified)(?:,.*)?", re.IGNORECASE
)


@dataclass(frozen=True)
class APRSISConfig:
    passcode: str
    callsign: str = SERVICE_CALLSIGN
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    software: str = "OpenQSP"
    version: str = "0.1"
    reconnect_delay: float = 5.0
    require_verified: bool = True
    filter: str | None = None

    def __post_init__(self) -> None:
        if not self.passcode:
            raise ValueError("APRS-IS passcode must be supplied externally")
        if not self.callsign:
            raise ValueError("APRS-IS callsign must be supplied")


def login_line(config: APRSISConfig) -> str:
    aprs_filter = config.filter or f"g/{config.callsign}"
    return (
        f"user {config.callsign} pass {config.passcode} vers "
        f"{config.software} {config.version} filter {aprs_filter}"
    )


def parse_logresp(line: str, callsign: str = SERVICE_CALLSIGN) -> bool | None:
    match = _LOGRESP_RE.fullmatch(line.strip())
    if match is None or match.group(1).upper() != callsign.upper():
        return None
    return match.group(2).lower() == "verified"


def parse_packet(line: str) -> tuple[str, str, str] | None:
    match = _PACKET_RE.fullmatch(line.rstrip("\r\n"))
    if match is None:
        return None
    source, addressee, body = match.groups()
    return source.upper(), addressee.strip().upper(), body


def format_packet(
    packet: OutboundPacket, *, destination: str = "APOQSP", path: str = "TCPIP*"
) -> str:
    return (
        f"{packet.source}>{destination},{path}::{packet.destination:<9}:{packet.body}"
    )


class APRSISClient:
    """Small reconnecting APRS-IS runner with all credentials injected."""

    def __init__(
        self,
        adapter: APRSAdapter,
        config: APRSISConfig,
        *,
        connector: Callable[..., object] = asyncio.open_connection,
    ) -> None:
        self.adapter, self.config, self.connector = adapter, config, connector
        self.running = False
        self._writer: asyncio.StreamWriter | None = None

    async def run(self) -> None:
        self.running = True
        while self.running:
            try:
                logger.info(
                    "APRS-IS: connecting to %s:%s as %s",
                    self.config.host,
                    self.config.port,
                    self.config.callsign,
                )
                reader, writer = await self.connector(
                    self.config.host, self.config.port
                )  # type: ignore[misc]
                self._writer = writer
                writer.write((login_line(self.config) + "\r\n").encode())
                await writer.drain()
                await self._connection(reader, writer)
                if self.running:
                    logger.warning(
                        "APRS-IS disconnected; reconnecting in %.1f seconds",
                        self.config.reconnect_delay,
                    )
                    await asyncio.sleep(self.config.reconnect_delay)
            except (OSError, ConnectionError, asyncio.IncompleteReadError):
                if self.running:
                    logger.warning(
                        "APRS-IS disconnected; reconnecting in %.1f seconds",
                        self.config.reconnect_delay,
                    )
                    await asyncio.sleep(self.config.reconnect_delay)
            except Exception:
                if self.running:
                    logger.exception("unexpected APRS-IS transport error; reconnecting")
                    await asyncio.sleep(self.config.reconnect_delay)
            finally:
                self._writer = None

    async def _connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        verified = False
        try:
            while self.running and not reader.at_eof():
                try:
                    raw = await asyncio.wait_for(reader.readline(), timeout=1.0)
                except TimeoutError:
                    raw = b""
                if raw:
                    line = raw.decode("ascii", "replace").rstrip()
                    status = parse_logresp(line, self.config.callsign)
                    if status is not None:
                        verified = status
                        if self.config.require_verified and not verified:
                            raise ConnectionError("APRS-IS login was not verified")
                        logger.info("APRS-IS: connected and verified")
                    packet = parse_packet(line)
                    if packet is not None and verified:
                        source, addressee, body = packet
                        if addressee == self.config.callsign.upper():
                            logger.info(
                                "APRS packet received: from=%s to=%s body=%r",
                                source,
                                addressee,
                                body,
                            )
                            try:
                                self.adapter.receive(source, body)
                            except Exception:
                                logger.exception("ignoring malformed APRS packet")
                for outbound in self.adapter.poll():
                    writer.write((format_packet(outbound) + "\r\n").encode())
                await writer.drain()
        finally:
            self.adapter.connection_lost()
            writer.close()
            await writer.wait_closed()

    def stop(self) -> None:
        self.running = False
        if self._writer is not None:
            self._writer.close()
