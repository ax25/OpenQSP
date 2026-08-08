"""M4.9 integrated conformance workflow for the minimum local node release."""

from __future__ import annotations
from pathlib import Path
import sys

TOOLS_ROOT = Path(__file__).parents[3] / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))
from client_sim import completed_cursor
from scenario_environment import LocalScenarioEnvironment, ScenarioEnvironment
from openqsp.protocol import (
    Bulletin,
    BulletinHeader,
    End,
    GetBulletin,
    GetNewBulletins,
    GetNewMessages,
    Message,
    Operation,
    SendMessage,
    Stored,
)

SENDER = "EA3AAA"
RECIPIENT = "EA3BBB"
UNRELATED = "EA3CCC"
MESSAGE_A = SendMessage(1786900001, RECIPIENT, "M4.9 message A")
MESSAGE_B = SendMessage(1786900002, RECIPIENT, "M4.9 message B")
BULLETIN = Bulletin(
    1296630017,
    1786900003,
    "EA9SRC",
    "M4.9 node bulletin",
    "Complete deterministic bulletin body",
)
SYNC_LIMIT = 20


def _cursor(responses, operation: Operation) -> int:
    cursor = completed_cursor(responses, operation)
    assert cursor is not None
    return cursor


def run_conformance_scenario(env: ScenarioEnvironment) -> None:
    """Exercise integrated M4 behavior through the scenario seam."""
    sender = env.client(SENDER)
    recipient = env.client(RECIPIENT)
    unrelated = env.client(UNRELATED)
    env.seed_bulletin(BULLETIN)
    assert sender.request(MESSAGE_A) == [Stored()]
    empty_messages = [End(Operation.GET_NEW_MESSAGES, 0, 0, False)]
    assert unrelated.request(GetNewMessages(0, SYNC_LIMIT)) == empty_messages
    assert sender.request(GetNewMessages(0, SYNC_LIMIT)) == empty_messages
    first_sync = recipient.request(GetNewMessages(0, SYNC_LIMIT))
    assert len(first_sync) == 2
    message_a, first_end = first_sync
    assert isinstance(message_a, Message)
    assert message_a == Message(
        message_a.sequence, MESSAGE_A.created_at, SENDER, RECIPIENT, MESSAGE_A.body
    )
    assert first_end == End(Operation.GET_NEW_MESSAGES, 1, message_a.sequence, False)
    message_cursor = _cursor(first_sync, Operation.GET_NEW_MESSAGES)
    message_a_sequence = message_a.sequence
    del sender, recipient, unrelated, first_sync
    env.restart_node()
    sender = env.client(SENDER)
    recipient = env.client(RECIPIENT)
    assert recipient.request(GetNewMessages(message_cursor, SYNC_LIMIT)) == [
        End(Operation.GET_NEW_MESSAGES, 0, message_cursor, False)
    ]
    assert sender.request(MESSAGE_B) == [Stored()]
    second_sync = recipient.request(GetNewMessages(message_cursor, SYNC_LIMIT))
    assert len(second_sync) == 2
    message_b, second_end = second_sync
    assert isinstance(message_b, Message)
    assert message_b.body == MESSAGE_B.body
    assert message_b.author == SENDER
    assert message_b.sequence == message_a_sequence + 1
    assert second_end == End(Operation.GET_NEW_MESSAGES, 1, message_b.sequence, False)
    latest_message_cursor = _cursor(second_sync, Operation.GET_NEW_MESSAGES)
    assert latest_message_cursor > message_cursor
    bulletin_sync = recipient.request(GetNewBulletins(0, SYNC_LIMIT))
    assert len(bulletin_sync) == 2
    header, bulletin_end = bulletin_sync
    assert isinstance(header, BulletinHeader)
    assert header == BulletinHeader(
        header.sequence, BULLETIN.created_at, BULLETIN.author, BULLETIN.title
    )
    assert bulletin_end == End(Operation.GET_NEW_BULLETINS, 1, header.sequence, False)
    bulletin_cursor = _cursor(bulletin_sync, Operation.GET_NEW_BULLETINS)
    assert recipient.request(GetBulletin(header.sequence)) == [
        Bulletin(
            header.sequence,
            BULLETIN.created_at,
            BULLETIN.author,
            BULLETIN.title,
            BULLETIN.body,
        )
    ]
    assert recipient.request(GetNewMessages(latest_message_cursor, SYNC_LIMIT)) == [
        End(Operation.GET_NEW_MESSAGES, 0, latest_message_cursor, False)
    ]
    assert recipient.request(GetNewBulletins(bulletin_cursor, SYNC_LIMIT)) == [
        End(Operation.GET_NEW_BULLETINS, 0, bulletin_cursor, False)
    ]


def test_milestone4_complete_local_node_workflow(tmp_path) -> None:
    run_conformance_scenario(LocalScenarioEnvironment(tmp_path / "milestone4.db"))
