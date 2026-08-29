"""APRS-IS line codec and resilient reconnecting asynchronous service connection."""

from __future__ import annotations

import asyncio
import logging
import random
import re
import socket
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
    reconnect_max_delay: float = 30.0
    reconnect_jitter: float = 0.2
    connect_timeout: float = 10.0
    login_timeout: float = 10.0
    idle_timeout: float = 120.0
    poll_interval: float = 1.0
    require_verified: bool = True
    filter: str | None = None
    tcp_keepalive: bool = True
    tcp_keepalive_idle: int = 60
    tcp_keepalive_interval: int = 20
    tcp_keepalive_count: int = 3

    def __post_init__(self) -> None:
        if not self.passcode:
            raise ValueError("APRS-IS passcode must be supplied externally")
        if not self.callsign:
            raise ValueError("APRS-IS callsign must be supplied")
        if self.reconnect_delay < 0:
            raise ValueError("APRS-IS reconnect delay cannot be negative")
        if self.reconnect_max_delay < self.reconnect_delay:
            raise ValueError("APRS-IS maximum reconnect delay is too small")
        if not 0 <= self.reconnect_jitter <= 1:
            raise ValueError("APRS-IS reconnect jitter must be between 0 and 1")
        if self.connect_timeout <= 0 or self.login_timeout <= 0:
            raise ValueError("APRS-IS connection timeouts must be positive")
        if self.idle_timeout <= 0 or self.poll_interval <= 0:
            raise ValueError("APRS-IS activity timeouts must be positive")


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
    """Reconnect APRS-IS promptly when login or link activity becomes unhealthy."""

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
        retry_delay = self.config.reconnect_delay
        while self.running:
            verified_session = False
            try:
                logger.info(
                    "APRS-IS: connecting to %s:%s as %s",
                    self.config.host,
                    self.config.port,
                    self.config.callsign,
                )
                reader, writer = await asyncio.wait_for(
                    self.connector(self.config.host, self.config.port),  # type: ignore[misc]
                    timeout=self.config.connect_timeout,
                )
                self._writer = writer
                self._configure_keepalive(writer)
                writer.write((login_line(self.config) + "\r\n").encode())
                await writer.drain()
                verified_session = await self._connection(reader, writer)
            except TimeoutError:
                if self.running:
                    logger.warning("APRS-IS connection attempt timed out")
            except (OSError, ConnectionError, asyncio.IncompleteReadError) as error:
                if self.running:
                    logger.warning("APRS-IS disconnected: %s", error)
            except Exception:
                if self.running:
                    logger.exception("unexpected APRS-IS transport error")
            finally:
                self._writer = None

            if not self.running:
                break

            if verified_session:
                retry_delay = self.config.reconnect_delay
            delay = self._jittered_delay(retry_delay)
            logger.warning(
                "APRS-IS reconnecting in %.1f seconds",
                delay,
            )
            await asyncio.sleep(delay)
            if not verified_session:
                retry_delay = min(
                    self.config.reconnect_max_delay,
                    max(self.config.reconnect_delay, retry_delay * 2),
                )

    async def _connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> bool:
        verified = False
        loop = asyncio.get_running_loop()
        connected_at = loop.time()
        last_rx = connected_at
        try:
            while self.running and not reader.at_eof():
                now = loop.time()
                deadline = (
                    connected_at + self.config.login_timeout
                    if not verified
                    else last_rx + self.config.idle_timeout
                )
                remaining = deadline - now
                if remaining <= 0:
                    if verified:
                        raise ConnectionError("APRS-IS connection became idle")
                    raise ConnectionError("APRS-IS login timed out")

                try:
                    raw = await asyncio.wait_for(
                        reader.readline(),
                        timeout=min(self.config.poll_interval, remaining),
                    )
                except TimeoutError:
                    raw = b""

                now = loop.time()
                if raw:
                    last_rx = now
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

                if not verified and now - connected_at >= self.config.login_timeout:
                    raise ConnectionError("APRS-IS login timed out")
                if verified and now - last_rx >= self.config.idle_timeout:
                    raise ConnectionError("APRS-IS connection became idle")

                # Never transmit application traffic until APRS-IS has verified
                # the login. This also keeps pending retry timers from starting
                # on a socket that may still be rejected.
                if verified:
                    for outbound in self.adapter.poll():
                        writer.write((format_packet(outbound) + "\r\n").encode())
                        logger.info(
                            "APRS packet sent: from=%s to=%s body=%r",
                            outbound.source,
                            outbound.destination,
                            outbound.body,
                        )
                    await writer.drain()

            if self.running and not verified:
                raise ConnectionError("APRS-IS closed before login verification")
            return verified
        finally:
            self.adapter.connection_lost()
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, ConnectionError):
                pass

    def _configure_keepalive(self, writer: asyncio.StreamWriter) -> None:
        if not self.config.tcp_keepalive:
            return
        get_extra_info = getattr(writer, "get_extra_info", None)
        if get_extra_info is None:
            return
        raw_socket = get_extra_info("socket")
        if raw_socket is None:
            return
        try:
            raw_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            options = (
                ("TCP_KEEPIDLE", self.config.tcp_keepalive_idle),
                ("TCP_KEEPINTVL", self.config.tcp_keepalive_interval),
                ("TCP_KEEPCNT", self.config.tcp_keepalive_count),
            )
            for name, value in options:
                option = getattr(socket, name, None)
                if option is not None:
                    raw_socket.setsockopt(socket.IPPROTO_TCP, option, value)
        except (OSError, AttributeError):
            logger.debug("APRS-IS TCP keepalive configuration unavailable")

    def _jittered_delay(self, delay: float) -> float:
        if delay <= 0 or self.config.reconnect_jitter == 0:
            return delay
        spread = delay * self.config.reconnect_jitter
        return max(0.0, random.uniform(delay - spread, delay + spread))

    def stop(self) -> None:
        self.running = False
        if self._writer is not None:
            self._writer.close()
