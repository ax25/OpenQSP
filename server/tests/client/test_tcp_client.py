"""Integration coverage for the reference TCP client."""

import asyncio
from openqsp.client import AuthenticationError, OpenQSPClient
from openqsp.client.cli import CommandSession
from openqsp.protocol import End, Message, Operation, Stored, decode_frame, encode_frame
from openqsp.server import ServerCore
from openqsp.server.tcp import TCPServer
from openqsp.storage import BulletinStore, Database, MessageStore


def _core(path):
    database = Database(path)
    database.initialize()
    return ServerCore(
        message_store=MessageStore(database), bulletin_store=BulletinStore(database)
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
                sender.send_message, "EA3BBB", "hello", created_at=456
            )
            assert ack == Stored()
            messages, end = await asyncio.to_thread(recipient.get_messages, 0, 5)
            assert messages == [Message(1, 456, "EA3AAA", "EA3BBB", "hello")]
            assert end.next_since == 1
            new_messages, next_end = await asyncio.to_thread(
                recipient.get_messages, end.next_since, 5
            )
            assert new_messages == []
            assert next_end.next_since == 1
            await asyncio.to_thread(sender.close)
            await asyncio.to_thread(recipient.close)
            assert not sender.connected and (not recipient.connected)

    asyncio.run(exercise())


def test_invalid_callsign_is_rejected_by_local_validation(tmp_path):

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
        writer.write(
            encode_frame(Message(7, 9, "EA3AAA", "EA3BBB", "pushed"), unsolicited=True)
        )
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
        expected = Message(7, 9, "EA3AAA", "EA3BBB", "pushed")
        assert received == [expected]
        assert client.get_events() == [expected]
        await asyncio.to_thread(client.close)
        server.close()
        await server.wait_closed()

    asyncio.run(exercise())


async def _read_frame(reader):
    header = await reader.readexactly(4)
    return header + await reader.readexactly(header[3])


async def _run_interleaving_peer(peer, operation):
    received = []

    async def handler(reader, writer):
        assert await reader.readline() == b"CALLSIGN EA3BBB\n"
        writer.write(b"OK\n")
        await writer.drain()
        request = decode_frame(await _read_frame(reader))
        assert isinstance(request, operation)
        await peer(writer, request)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    client = OpenQSPClient(
        "127.0.0.1",
        server.sockets[0].getsockname()[1],
        timeout=2,
        event_handler=received.append,
    )
    await asyncio.to_thread(client.connect)
    await asyncio.to_thread(client.authenticate, "EA3BBB")
    return (server, client, received)


def test_unsolicited_message_interleaved_before_send_ack_is_an_event():
    pushed = Message(7, 700, "EA3AAA", "EA3BBB", "while sending")

    async def peer(writer, request):
        writer.write(encode_frame(pushed, unsolicited=True))
        writer.write(encode_frame(Stored()))
        await writer.drain()

    async def exercise():
        from openqsp.protocol import SendMessage

        server, client, received = await _run_interleaving_peer(peer, SendMessage)
        ack = await asyncio.to_thread(
            client.send_message, "EA3AAA", "request", created_at=701
        )
        assert ack == Stored()
        assert received == [pushed]
        assert client.get_events() == [pushed]
        client.close()
        server.close()
        await server.wait_closed()

    asyncio.run(exercise())


def test_unsolicited_message_interleaved_with_retrieval_is_not_a_response():
    pushed = Message(8, 800, "EA3CCC", "EA3BBB", "proactive")
    response = Message(9, 900, "EA3AAA", "EA3BBB", "retrieved")

    async def peer(writer, request):
        writer.write(encode_frame(pushed, unsolicited=True))
        writer.write(encode_frame(response))
        writer.write(encode_frame(End(Operation.GET_NEW_MESSAGES, 1, 9, False)))
        await writer.drain()

    async def exercise():
        from openqsp.protocol import GetNewMessages

        server, client, received = await _run_interleaving_peer(peer, GetNewMessages)
        messages, end = await asyncio.to_thread(client.get_messages, 4, 5)
        assert messages == [response]
        assert end == End(Operation.GET_NEW_MESSAGES, 1, 9, False)
        assert received == [pushed]
        assert client.get_events() == [pushed]
        client.close()
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
