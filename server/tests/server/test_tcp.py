"""Loopback tests for the minimal development TCP transport."""

import asyncio
from openqsp.protocol import (
    End,
    GetNewMessages,
    Message,
    Operation,
    SendMessage,
    Stored,
    decode_frame,
    encode_frame,
)
from openqsp.server import ServerCore
from openqsp.server.tcp import HANDSHAKE_ERROR, HANDSHAKE_OK, TCPServer
from openqsp.storage import BulletinStore, Database, MessageStore


def _core(database_path) -> ServerCore:
    database = Database(database_path)
    database.initialize()
    return ServerCore(
        message_store=MessageStore(database), bulletin_store=BulletinStore(database)
    )


async def _connect(server: TCPServer, callsign: str = "K1ABC"):
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"CALLSIGN {callsign}\n".encode("ascii"))
    await writer.drain()
    assert await reader.readline() == HANDSHAKE_OK
    return (reader, writer)


async def _read_frame(reader: asyncio.StreamReader) -> bytes:
    header = await reader.readexactly(4)
    return header + await reader.readexactly(header[3])


def test_server_accepts_valid_handshake_and_rejects_invalid_one(tmp_path):

    async def exercise():
        async with TCPServer(_core(tmp_path / "node.db"), port=0) as server:
            reader, writer = await _connect(server)
            writer.close()
            await writer.wait_closed()
            assert await reader.read() == b""
            port = server.sockets[0].getsockname()[1]
            invalid_reader, invalid_writer = await asyncio.open_connection(
                "127.0.0.1", port
            )
            invalid_writer.write(b"CALLSIGN lowercase\n")
            await invalid_writer.drain()
            assert await invalid_reader.readline() == HANDSHAKE_ERROR
            assert await invalid_reader.read() == b""
            invalid_writer.close()
            await invalid_writer.wait_closed()

    asyncio.run(exercise())


def test_complete_request_reaches_real_core_and_response_returns(tmp_path):

    async def exercise():
        async with TCPServer(_core(tmp_path / "node.db"), port=0) as server:
            reader, writer = await _connect(server)
            request = encode_frame(SendMessage(20, "N0CALL", "hello"))
            writer.write(request)
            await writer.drain()
            assert decode_frame(await _read_frame(reader)) == Stored()
            writer.close()
            await writer.wait_closed()

    asyncio.run(exercise())


def test_maximum_size_valid_request_does_not_stall_stream_reader(tmp_path):

    async def exercise():
        async with TCPServer(_core(tmp_path / "node.db"), port=0) as server:
            reader, writer = await _connect(server)
            request = encode_frame(SendMessage(21, "N0CALL123456", "x" * 208))
            for offset in range(0, len(request), 16):
                writer.write(request[offset : offset + 16])
                await writer.drain()
                await asyncio.sleep(0)
            response = await asyncio.wait_for(_read_frame(reader), timeout=1)
            assert decode_frame(response) == Stored()
            writer.close()
            await writer.wait_closed()

    asyncio.run(exercise())


def test_fragmented_frame_is_reassembled(tmp_path):

    async def exercise():
        async with TCPServer(_core(tmp_path / "node.db"), port=0) as server:
            reader, writer = await _connect(server)
            frame = encode_frame(GetNewMessages(0, 5))
            for byte in frame:
                writer.write(bytes((byte,)))
                await writer.drain()
                await asyncio.sleep(0)
            assert decode_frame(await _read_frame(reader)) == End(
                Operation.GET_NEW_MESSAGES, 0, 0, False
            )
            writer.close()
            await writer.wait_closed()

    asyncio.run(exercise())


def test_coalesced_and_sequential_frames_are_processed_in_order(tmp_path):

    async def exercise():
        async with TCPServer(_core(tmp_path / "node.db"), port=0) as server:
            reader, writer = await _connect(server)
            first = encode_frame(SendMessage(10, "N0CALL", "one"))
            second = encode_frame(SendMessage(11, "N0CALL", "two"))
            writer.write(first + second)
            await writer.drain()
            assert decode_frame(await _read_frame(reader)) == Stored()
            assert decode_frame(await _read_frame(reader)) == Stored()
            writer.write(encode_frame(GetNewMessages(0, 5)))
            await writer.drain()
            assert decode_frame(await _read_frame(reader)) == End(
                Operation.GET_NEW_MESSAGES, 0, 0, False
            )
            writer.close()
            await writer.wait_closed()

    asyncio.run(exercise())


def test_two_clients_are_served_concurrently(tmp_path):

    async def request(server, callsign):
        reader, writer = await _connect(server, callsign)
        writer.write(encode_frame(GetNewMessages(0, 5)))
        await writer.drain()
        response = decode_frame(await _read_frame(reader))
        writer.close()
        await writer.wait_closed()
        return response

    async def exercise():
        async with TCPServer(_core(tmp_path / "node.db"), port=0) as server:
            responses = await asyncio.gather(
                request(server, "K1ABC"), request(server, "N0CALL")
            )
            assert responses == [
                End(Operation.GET_NEW_MESSAGES, 0, 0, False),
                End(Operation.GET_NEW_MESSAGES, 0, 0, False),
            ]

    asyncio.run(exercise())


def test_partial_disconnect_does_not_affect_another_client(tmp_path):

    async def exercise():
        async with TCPServer(_core(tmp_path / "node.db"), port=0) as server:
            _, partial_writer = await _connect(server)
            partial_writer.write(encode_frame(GetNewMessages(0, 5))[:6])
            await partial_writer.drain()
            partial_writer.close()
            await partial_writer.wait_closed()
            reader, writer = await _connect(server, "N0CALL")
            writer.write(encode_frame(GetNewMessages(0, 5)))
            await writer.drain()
            assert isinstance(decode_frame(await _read_frame(reader)), End)
            writer.close()
            await writer.wait_closed()

    asyncio.run(exercise())


def test_state_survives_disconnect_and_reconnect_with_same_stores(tmp_path):

    async def exercise():
        async with TCPServer(_core(tmp_path / "node.db"), port=0) as server:
            _, sender = await _connect(server, "K1ABC")
            sender.write(encode_frame(SendMessage(100, "N0CALL", "durable")))
            await sender.drain()
            sender.close()
            await sender.wait_closed()
            reader, recipient = await _connect(server, "N0CALL")
            recipient.write(encode_frame(GetNewMessages(0, 5)))
            await recipient.drain()
            message = decode_frame(await _read_frame(reader))
            end = decode_frame(await _read_frame(reader))
            assert message == Message(1, 100, "K1ABC", "N0CALL", "durable")
            assert end == End(Operation.GET_NEW_MESSAGES, 1, 1, False)
            recipient.close()
            await recipient.wait_closed()

    asyncio.run(exercise())


def test_transport_forwards_without_decoding_or_operation_knowledge():

    class RecordingCore:

        def handle_frame(self, callsign, frame):
            seen.append((callsign, frame))
            return [b"\x01\x7f\x00\x00"]

    async def exercise():
        server = TCPServer(RecordingCore(), port=0)
        async with server:
            reader, writer = await _connect(server)
            opaque_frame = b"\x01\x7f\x00\x03abc"
            writer.write(opaque_frame)
            await writer.drain()
            assert await _read_frame(reader) == b"\x01\x7f\x00\x00"
            assert seen == [("K1ABC", opaque_frame)]
            writer.close()
            await writer.wait_closed()

    seen = []
    asyncio.run(exercise())
