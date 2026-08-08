"""Integration coverage for the reference TCP client."""

import asyncio

from openqsp.client import AuthenticationError, OpenQSPClient
from openqsp.client.cli import CommandSession
from openqsp.protocol import AckStatus, Message, encode_frame
from openqsp.server import ServerCore
from openqsp.server.tcp import TCPServer
from openqsp.storage import BulletinStore, Database, MessageStore


def _core(path):
    database = Database(path)
    database.initialize()
    return ServerCore(
        message_store=MessageStore(database),
        bulletin_store=BulletinStore(database),
    )


async def _client(server, callsign, **kwargs):
    port = server.sockets[0].getsockname()[1]
    client = OpenQSPClient("127.0.0.1", port, timeout=2, **kwargs)
    await asyncio.to_thread(client.connect)
    await asyncio.to_thread(client.authenticate, callsign)
    return client


def test_connect_authenticate_send_retrieve_and_clean_disconnect(tmp_path):
    async def exercise():
        async with TCPServer(_core(tmp_path / "node.db"), port=0) as server:
            sender = await _client(server, "EA3AAA")
            recipient = await _client(server, "EA3BBB")
            assert sender.connected and sender.authenticated

            ack = await asyncio.to_thread(
                sender.send_message,
                "EA3BBB",
                "hello",
                message_id=123,
                created_at=456,
            )
            assert ack.status is AckStatus.STORED
            messages, end = await asyncio.to_thread(recipient.get_messages, 0, 5)
            assert messages == [Message(1, 123, 456, "EA3AAA", "EA3BBB", "hello")]
            assert end.next_since == 1
            new_messages, next_end = await asyncio.to_thread(
                recipient.get_messages, end.next_since, 5
            )
            assert new_messages == []
            assert next_end.next_since == 1

            await asyncio.to_thread(sender.close)
            await asyncio.to_thread(recipient.close)
            assert not sender.connected and not recipient.connected

    asyncio.run(exercise())


def test_invalid_callsign_authentication_is_rejected(tmp_path):
    async def exercise():
        async with TCPServer(_core(tmp_path / "node.db"), port=0) as server:
            port = server.sockets[0].getsockname()[1]
            client = OpenQSPClient("127.0.0.1", port)
            await asyncio.to_thread(client.connect)
            try:
                await asyncio.to_thread(client.authenticate, "lowercase")
            except AuthenticationError as error:
                assert "uppercase" in str(error)
            else:
                raise AssertionError("authentication unexpectedly succeeded")
            client.close()

    asyncio.run(exercise())


def test_background_reader_delivers_unsolicited_protocol_event():
    received = []

    async def peer(reader, writer):
        assert await reader.readline() == b"CALLSIGN EA3BBB\n"
        writer.write(b"OK\n")
        await writer.drain()
        writer.write(encode_frame(Message(7, 8, 9, "EA3AAA", "EA3BBB", "pushed")))
        await writer.drain()
        await asyncio.sleep(0.2)
        writer.close()
        await writer.wait_closed()

    async def exercise():
        server = await asyncio.start_server(peer, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        client = OpenQSPClient("127.0.0.1", port, event_handler=received.append)
        await asyncio.to_thread(client.connect)
        await asyncio.to_thread(client.authenticate, "EA3BBB")
        for _ in range(20):
            if received:
                break
            await asyncio.sleep(0.01)
        expected = Message(7, 8, 9, "EA3AAA", "EA3BBB", "pushed")
        assert received == [expected]
        assert client.get_events() == [expected]
        await asyncio.to_thread(client.close)
        server.close()
        await server.wait_closed()

    asyncio.run(exercise())


def test_cli_command_parsing_and_usage():
    class Client:
        endpoint = ("node.example", 8023)
        connected = True
        callsign = "EA3AAA"

    session = CommandSession(Client())
    assert session.execute("status") == (
        True,
        "Connected: yes\nAuthenticated: EA3AAA\nServer: node.example:8023",
    )
    assert "SEND_MESSAGE" in session.execute("services")[1]
    assert session.execute("send EA3BBB")[1].startswith("Usage:")
    assert session.execute("unknown")[1].startswith("Unknown command:")
    assert session.execute("quit") == (False, "")
