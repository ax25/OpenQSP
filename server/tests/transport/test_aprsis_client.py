from __future__ import annotations

import asyncio

import pytest
from openqsp.protocol import GetCapabilities, encode_frame
from openqsp.server import ServerCore
from openqsp.transport.aprs import AdapterConfig, APRSAdapter
from openqsp.transport.aprs.aprsis import APRSISClient, APRSISConfig, parse_packet
from openqsp.transport.aprs.carriage import APRSFragment, fragment_frame


class FakeReader:
    def __init__(self, lines: list[str]) -> None:
        self.lines = [f"{line}\r\n".encode() for line in lines]

    def at_eof(self) -> bool:
        return not self.lines

    async def readline(self) -> bytes:
        return self.lines.pop(0) if self.lines else b""


class HangingReader:
    def __init__(self, lines: list[str] | None = None) -> None:
        self.lines = [f"{line}\r\n".encode() for line in (lines or [])]

    def at_eof(self) -> bool:
        return False

    async def readline(self) -> bytes:
        if self.lines:
            return self.lines.pop(0)
        await asyncio.sleep(3600)
        return b""


class FakeWriter:
    def __init__(self) -> None:
        self.data: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.data.append(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


def inbound_line(peer: str = "EA3AAA-10") -> str:
    fragment = fragment_frame(encode_frame(GetCapabilities()), "0A7")[0]
    body = APRSFragment(
        fragment.transaction_id,
        fragment.index,
        fragment.total,
        fragment.data,
        "4F",
    ).body
    return f"{peer}>APRS,TCPIP*::OPENQSP  :{body}"


def test_connection_login_receive_emit_ignore_and_cleanup_without_network(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    config = APRSISConfig(passcode="secret-from-environment")
    client = APRSISClient(adapter, config)
    client.running = True
    reader = FakeReader(
        [
            "# logresp OPENQSP verified, server LOCAL",
            "malformed",
            inbound_line().replace("OPENQSP  ", "OTHER    "),
            "EA3GNU-7>APRS,TCPIP*::OTHER    :Do not log this body",
            "EA3GNU-7>APRS,TCPIP*::OPENQSP  :Hola OpenQSP",
            inbound_line(),
        ]
    )
    writer = FakeWriter()

    calls = 0

    async def connector(_host: str, _port: int):
        nonlocal calls
        calls += 1
        if calls == 1:
            return reader, writer
        client.stop()
        raise OSError("test complete")

    client.connector = connector
    asyncio.run(client.run())
    output = b"".join(writer.data).decode()
    assert output.startswith(
        "user OPENQSP pass secret-from-environment vers OpenQSP 0.1 "
        "filter g/OPENQSP"
    )
    assert "OPENQSP>APOQSP,TCPIP*::EA3AAA-10:ack4F" in output
    assert (
        "APRS packet received: from=EA3GNU-7 to=OPENQSP igate=- body='Hola OpenQSP'"
        in caplog.text
    )
    assert "Do not log this body" not in caplog.text
    assert "secret-from-environment" not in caplog.text
    assert writer.closed
    assert adapter.queued_count == adapter.pending_count == 0
    # Replay/reassembly are socket-independent and remain TTL bounded.
    assert len(adapter.replay) == 1


def test_unverified_login_is_rejected_and_link_state_is_cleaned() -> None:
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    adapter.queue_frame("EA3AAA", encode_frame(GetCapabilities()))
    client = APRSISClient(adapter, APRSISConfig(passcode="external"))
    client.running = True
    writer = FakeWriter()
    with pytest.raises(ConnectionError, match="not verified"):
        asyncio.run(
            client._connection(
                FakeReader(["# logresp OPENQSP unverified, server LOCAL"]), writer
            )
        )
    assert writer.closed
    assert adapter.queued_count == adapter.pending_count == 0


def test_connection_writes_and_logs_outbound_ack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    client = APRSISClient(adapter, APRSISConfig(passcode="external"))
    client.running = True
    writer = FakeWriter()

    asyncio.run(
        client._connection(
            FakeReader(
                [
                    "# logresp OPENQSP verified, server LOCAL",
                    "EA3GNU-5>APRS,TCPIP*::OPENQSP  :Hola prueba radio{2",
                ]
            ),
            writer,
        )
    )

    assert writer.data == [b"OPENQSP>APOQSP,TCPIP*::EA3GNU-5 :ack2\r\n"]
    assert (
        "APRS packet sent: from=OPENQSP to=EA3GNU-5 body='ack2'" in caplog.text
    )


def test_run_reconnects_after_connector_failure_without_real_sleep() -> None:
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    config = APRSISConfig(
        passcode="external",
        reconnect_delay=0,
        reconnect_max_delay=0,
    )
    calls = 0
    writer = FakeWriter()

    async def connector(_host: str, _port: int):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("temporary local failure")
        if calls == 2:
            return FakeReader(["# logresp OPENQSP verified, server LOCAL"]), writer
        client.stop()
        raise OSError("stop")

    client = APRSISClient(adapter, config, connector=connector)
    asyncio.run(client.run())
    assert calls == 3
    assert writer.data[0].decode().startswith(
        "user OPENQSP pass external vers OpenQSP 0.1 filter g/OPENQSP"
    )
    assert writer.closed


def test_login_watchdog_closes_socket_that_never_verifies() -> None:
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    client = APRSISClient(
        adapter,
        APRSISConfig(
            passcode="external",
            login_timeout=0.03,
            idle_timeout=1,
            poll_interval=0.005,
        ),
    )
    client.running = True
    writer = FakeWriter()

    with pytest.raises(ConnectionError, match="login timed out"):
        asyncio.run(client._connection(HangingReader(), writer))

    assert writer.closed


def test_idle_watchdog_reconnects_verified_but_silent_socket() -> None:
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    client = APRSISClient(
        adapter,
        APRSISConfig(
            passcode="external",
            login_timeout=1,
            idle_timeout=0.03,
            poll_interval=0.005,
        ),
    )
    client.running = True
    writer = FakeWriter()

    with pytest.raises(ConnectionError, match="became idle"):
        asyncio.run(
            client._connection(
                HangingReader(["# logresp OPENQSP verified, server LOCAL"]),
                writer,
            )
        )

    assert writer.closed


def test_pending_application_packet_is_not_sent_before_verified_login() -> None:
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    adapter.queue_frame("EA3AAA", encode_frame(GetCapabilities()))
    client = APRSISClient(
        adapter,
        APRSISConfig(
            passcode="external",
            login_timeout=0.03,
            idle_timeout=1,
            poll_interval=0.005,
        ),
    )
    client.running = True
    writer = FakeWriter()

    with pytest.raises(ConnectionError, match="login timed out"):
        asyncio.run(client._connection(HangingReader(), writer))

    assert writer.data == []
    assert adapter.queued_count == adapter.pending_count == 0


def test_parse_packet_extracts_igate_after_qa_construct() -> None:
    parsed = parse_packet(
        "EA3GNU-5>APOQSP,WIDE1-1,WIDE2-1,qAR,EA3XYZ-10::OPENQSP  :Hola"
    )

    assert parsed == ("EA3GNU-5", "OPENQSP", "Hola", "EA3XYZ-10")


def test_last_igate_is_tracked_by_base_callsign_and_not_overwritten_by_tcp() -> None:
    adapter = APRSAdapter(ServerCore(), config=AdapterConfig(min_interval=0))
    client = APRSISClient(adapter, APRSISConfig(passcode="external"))
    client.running = True
    writer = FakeWriter()

    asyncio.run(
        client._connection(
            FakeReader(
                [
                    "# logresp OPENQSP verified, server LOCAL",
                    "EA3GNU-5>APOQSP,WIDE1-1,qAR,EA3IGT-10::OPENQSP  :Hola RF",
                    "EA3GNU-7>APOQSP,TCPIP*::OPENQSP  :Hola IS",
                ]
            ),
            writer,
        )
    )

    assert client.last_igate_for("EA3GNU") == "EA3IGT-10"
    assert client.last_igate_for("EA3GNU-7") == "EA3IGT-10"
