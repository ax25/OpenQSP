"""Production identity/session/capability M6 conformance workflow."""

import asyncio
import sqlite3

import pytest
from openqsp.client import AuthenticationError, OpenQSPClient
from openqsp.protocol import (
    IMPLEMENTED_CAPABILITIES,
    PROTOCOL_VERSION,
    Capabilities,
    Capability,
    GetNewMessages,
    Message,
    SendMessage,
    Stored,
    decode_frame,
    encode_frame,
)
from openqsp.server import ServerCore
from openqsp.server.tcp import TCPServer
from openqsp.storage import (
    AccountExistsError,
    AccountStore,
    BulletinStore,
    Database,
    InvalidCredentialsError,
    MessageStore,
)


def _node(path):
    database = Database(path)
    database.initialize()
    accounts = AccountStore(database)
    core = ServerCore(
        message_store=MessageStore(database), bulletin_store=BulletinStore(database)
    )
    return database, accounts, core


def test_account_security_normalization_and_restart(tmp_path):
    path = tmp_path / "node.db"
    database, accounts, _ = _node(path)
    assert accounts.create_account("ea3aaa-7", "correct horse") == "EA3AAA"
    assert accounts.authenticate("EA3AAA/P", "correct horse") == "EA3AAA"
    with pytest.raises(InvalidCredentialsError, match="invalid credentials"):
        accounts.authenticate("EA3AAA", "wrong")
    with pytest.raises(InvalidCredentialsError, match="invalid credentials"):
        accounts.authenticate("N0NONE", "wrong")
    with pytest.raises(AccountExistsError):
        accounts.create_account("EA3AAA", "another")
    with pytest.raises(InvalidCredentialsError):
        accounts.create_account("invalid", "password")
    with pytest.raises(InvalidCredentialsError):
        accounts.authenticate([], object())

    with sqlite3.connect(database.path) as connection:
        stored = connection.execute("SELECT password_hash FROM accounts").fetchone()[0]
    assert "correct horse" not in stored
    assert stored.startswith("pbkdf2_sha256$")
    assert (
        AccountStore(Database(path)).authenticate("EA3AAA", "correct horse") == "EA3AAA"
    )


async def _client(server, callsign, password):
    port = server.sockets[0].getsockname()[1]
    client = OpenQSPClient("127.0.0.1", port, timeout=3)
    await asyncio.to_thread(client.connect)
    await asyncio.to_thread(client.authenticate, callsign, password)
    return client


def test_production_two_user_push_capabilities_restart(tmp_path):
    async def exercise():
        path = tmp_path / "node.db"
        _, accounts, core = _node(path)
        accounts.create_account("EA3AAA", "alpha password")
        accounts.create_account("EA3BBB", "bravo password")

        server = TCPServer(core, port=0, account_store=accounts)
        async with server:
            sender = await _client(server, "EA3AAA", "alpha password")
            recipient = await _client(server, "EA3BBB", "bravo password")
            second_recipient = await _client(server, "EA3BBB-2", "bravo password")
            capabilities = await asyncio.to_thread(sender.get_capabilities)
            assert capabilities == Capabilities(
                PROTOCOL_VERSION, int(IMPLEMENTED_CAPABILITIES)
            )
            assert capabilities.capabilities & Capability.PROACTIVE_PRIVATE_MESSAGES

            await asyncio.to_thread(
                sender.send_message, "EA3BBB", "durable and pushed", created_at=1234
            )
            expected = Message(1, 1234, "EA3AAA", "EA3BBB", "durable and pushed")
            for _ in range(50):
                if recipient.get_events() and second_recipient.get_events():
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("both active sessions did not receive push")
            messages, end = await asyncio.to_thread(recipient.get_messages, 0, 5)
            assert messages == [expected]
            assert end.next_since == 1
            await asyncio.to_thread(sender.close)
            await asyncio.to_thread(recipient.close)
            await asyncio.to_thread(second_recipient.close)
            for _ in range(50):
                if server.sessions.active_count == 0:
                    break
                await asyncio.sleep(0.01)
            assert server.sessions.active_count == 0

        # Full node reconstruction proves both credential and mailbox persistence.
        _, restarted_accounts, restarted_core = _node(path)
        async with TCPServer(
            restarted_core, port=0, account_store=restarted_accounts
        ) as restarted:
            recipient = await _client(restarted, "EA3BBB", "bravo password")
            messages, end = await asyncio.to_thread(recipient.get_messages, 0, 5)
            assert messages == [
                Message(1, 1234, "EA3AAA", "EA3BBB", "durable and pushed")
            ]
            assert end.next_since == 1
            await asyncio.to_thread(recipient.close)

    asyncio.run(exercise())


def test_listener_failure_is_logged_after_durable_acceptance(tmp_path, caplog):
    _, _, core = _node(tmp_path / "node.db")

    def broken_listener(message):
        raise RuntimeError(f"cannot push message {message.sequence}")

    core.add_message_listener(broken_listener)
    response = core.handle_frame(
        "EA3AAA", encode_frame(SendMessage(1234, "EA3BBB", "still durable"))
    )

    assert [decode_frame(frame) for frame in response] == [Stored()]
    messages = core.handle_frame(
        "EA3BBB", encode_frame(GetNewMessages(0, 5))
    )
    assert decode_frame(messages[0]) == Message(
        1, 1234, "EA3AAA", "EA3BBB", "still durable"
    )
    assert "message listener failed after durable acceptance" in caplog.text


def test_production_auth_rejects_all_invalid_inputs_equally(tmp_path):
    async def exercise():
        _, accounts, core = _node(tmp_path / "node.db")
        accounts.create_account("EA3AAA", "right password")
        async with TCPServer(core, port=0, account_store=accounts) as server:
            for callsign, password in (("EA3AAA", "wrong"), ("EA3BBB", "wrong")):
                port = server.sockets[0].getsockname()[1]
                client = OpenQSPClient("127.0.0.1", port, timeout=2)
                await asyncio.to_thread(client.connect)
                with pytest.raises(AuthenticationError, match="invalid credentials"):
                    await asyncio.to_thread(client.authenticate, callsign, password)

            reader, writer = await asyncio.open_connection(
                "127.0.0.1", server.sockets[0].getsockname()[1]
            )
            writer.write(b"AUTH malformed\n")
            await writer.drain()
            assert await reader.readline() == b"ERROR\n"
            assert await reader.read() == b""
            writer.close()
            await writer.wait_closed()

    asyncio.run(exercise())
