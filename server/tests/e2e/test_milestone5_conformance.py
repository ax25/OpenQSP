"""M5.5 conformance workflow through the complete development TCP path."""

import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).parents[3] / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from client_sim import completed_cursor
from openqsp.protocol import (
    Bulletin,
    BulletinHeader,
    End,
    Error,
    ErrorCode,
    GetBulletin,
    GetNewBulletins,
    GetNewMessages,
    Message,
    Operation,
    SendMessage,
    Stored,
)
from scenario_environment import RemoteScenarioEnvironment

SENDER = "EA3AAA"
RECIPIENT = "EA3BBB"
UNRELATED = "EA3CCC"
MESSAGE_A = SendMessage(1_786_910_001, RECIPIENT, "M5.5 message A")
MESSAGE_B = SendMessage(1_786_910_002, RECIPIENT, "M5.5 message B")
MESSAGE_C = SendMessage(1_786_910_003, RECIPIENT, "M5.5 after restart")
BULLETIN = Bulletin(
    1,
    1_786_910_004,
    "EA9SRC",
    "M5.5 node bulletin",
    "Persistent bulletin body",
)
LIMIT = 20


def _cursor(responses, operation: Operation) -> int:
    cursor = completed_cursor(responses, operation)
    assert cursor is not None
    return cursor


def _assert_message(response, request: SendMessage, sequence: int) -> None:
    assert response == Message(sequence, request.created_at,
        SENDER,
        RECIPIENT,
        request.body,
    )


def test_milestone5_complete_internet_transport_workflow(tmp_path) -> None:
    """Prove all v0.1 operations, reconnects, and restart over real TCP."""
    env = RemoteScenarioEnvironment(tmp_path / "milestone5.db")
    try:
        sender = env.client(SENDER)
        recipient = env.client(RECIPIENT)
        unrelated = env.client(UNRELATED)
        env.seed_bulletin(BULLETIN)

        assert sender.request(MESSAGE_A) == [
            Stored()
        ]

        first_sync = recipient.request(GetNewMessages(0, LIMIT))
        assert len(first_sync) == 2
        first_message, first_end = first_sync
        assert isinstance(first_message, Message)
        _assert_message(first_message, MESSAGE_A, first_message.sequence)
        assert first_end == End(
            Operation.GET_NEW_MESSAGES, 1, first_message.sequence, False
        )
        first_cursor = _cursor(first_sync, Operation.GET_NEW_MESSAGES)

        # These calls use new sockets. Callsign identity, rather than either
        # connection, selects the durable mailbox.
        assert unrelated.request(GetNewMessages(0, LIMIT)) == [
            End(Operation.GET_NEW_MESSAGES, 0, 0, False)
        ]
        assert sender.request(MESSAGE_B) == [
            Stored()
        ]
        second_sync = recipient.request(GetNewMessages(first_cursor, LIMIT))
        assert len(second_sync) == 2
        second_message, second_end = second_sync
        assert isinstance(second_message, Message)
        _assert_message(second_message, MESSAGE_B, first_message.sequence + 1)
        assert second_end == End(
            Operation.GET_NEW_MESSAGES, 1, second_message.sequence, False
        )
        pre_restart_cursor = _cursor(second_sync, Operation.GET_NEW_MESSAGES)
        assert pre_restart_cursor > first_cursor
        assert recipient.request(GetNewMessages(pre_restart_cursor, LIMIT)) == [
            End(Operation.GET_NEW_MESSAGES, 0, pre_restart_cursor, False)
        ]

        bulletin_sync = recipient.request(GetNewBulletins(0, LIMIT))
        assert len(bulletin_sync) == 2
        header, bulletin_end = bulletin_sync
        assert isinstance(header, BulletinHeader)
        assert header == BulletinHeader(header.sequence, BULLETIN.created_at,
            BULLETIN.author,
            BULLETIN.title,
        )
        assert bulletin_end == End(
            Operation.GET_NEW_BULLETINS, 1, header.sequence, False
        )
        bulletin_cursor = _cursor(bulletin_sync, Operation.GET_NEW_BULLETINS)
        assert recipient.request(GetBulletin(header.sequence)) == [BULLETIN]
        assert recipient.request(GetBulletin(0x4D55FFFF)) == [
            Error(Operation.GET_BULLETIN, ErrorCode.NOT_FOUND, "bulletin not found")
        ]

        # Stop the listener and discard Core/store/client runtime objects. The
        # environment reconstructs the complete node against the same SQLite DB.
        del sender, recipient, unrelated
        env.restart_node()
        sender = env.client(SENDER)
        recipient = env.client(RECIPIENT)

        persisted = recipient.request(GetNewMessages(0, LIMIT))
        assert len(persisted) == 3
        _assert_message(persisted[0], MESSAGE_A, first_message.sequence)
        _assert_message(persisted[1], MESSAGE_B, second_message.sequence)
        assert persisted[-1] == End(
            Operation.GET_NEW_MESSAGES, 2, pre_restart_cursor, False
        )
        assert recipient.request(GetNewMessages(pre_restart_cursor, LIMIT)) == [
            End(Operation.GET_NEW_MESSAGES, 0, pre_restart_cursor, False)
        ]
        assert recipient.request(GetNewBulletins(bulletin_cursor, LIMIT)) == [
            End(Operation.GET_NEW_BULLETINS, 0, bulletin_cursor, False)
        ]
        assert recipient.request(GetBulletin(BULLETIN.sequence)) == [BULLETIN]

        assert sender.request(MESSAGE_C) == [
            Stored()
        ]
        post_restart = recipient.request(
            GetNewMessages(pre_restart_cursor, LIMIT)
        )
        assert len(post_restart) == 2
        third_message, third_end = post_restart
        assert isinstance(third_message, Message)
        _assert_message(third_message, MESSAGE_C, second_message.sequence + 1)
        assert third_message.sequence > second_message.sequence
        assert third_end == End(
            Operation.GET_NEW_MESSAGES, 1, third_message.sequence, False
        )
        final_cursor = _cursor(post_restart, Operation.GET_NEW_MESSAGES)
        assert final_cursor > pre_restart_cursor
        assert recipient.request(GetNewMessages(final_cursor, LIMIT)) == [
            End(Operation.GET_NEW_MESSAGES, 0, final_cursor, False)
        ]
    finally:
        env.close()
