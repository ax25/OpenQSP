"""M4.9 integrated conformance workflow for the minimum local node release."""

from __future__ import annotations

import gc
from pathlib import Path
import sys

TOOLS_ROOT = Path(__file__).parents[3] / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from client_sim import LocalCoreClient, completed_cursor  # noqa: E402
from openqsp.protocol import (  # noqa: E402
    Ack,
    AckStatus,
    Bulletin,
    BulletinHeader,
    End,
    GetBulletin,
    GetNewBulletins,
    GetNewMessages,
    Message,
    Operation,
    SendMessage,
    encode_frame,
)
from openqsp.server import ServerCore  # noqa: E402
from openqsp.storage import BulletinStore, Database, MessageStore  # noqa: E402


SENDER = "EA3AAA"
RECIPIENT = "EA3BBB"
UNRELATED = "EA3CCC"
MESSAGE_A = SendMessage(0x4D490001, 1_786_900_001, RECIPIENT, "M4.9 message A")
MESSAGE_B = SendMessage(0x4D490002, 1_786_900_002, RECIPIENT, "M4.9 message B")
BULLETIN = Bulletin(
    0x4D490101,
    1_786_900_003,
    "EA9SRC",
    "M4.9 node bulletin",
    "Complete deterministic bulletin body",
)
SYNC_LIMIT = 20


def _new_node(database_path: Path):
    database = Database(database_path)
    database.initialize()
    messages = MessageStore(database)
    bulletins = BulletinStore(database)
    core = ServerCore(message_store=messages, bulletin_store=bulletins)
    return database, messages, bulletins, core


def _cursor(responses, operation: Operation) -> int:
    cursor = completed_cursor(responses, operation)
    assert cursor is not None
    return cursor


def test_milestone4_complete_local_node_workflow(tmp_path) -> None:
    database_path = tmp_path / "milestone4.db"
    database, messages, bulletins, core = _new_node(database_path)
    sender = LocalCoreClient(core, SENDER)
    recipient = LocalCoreClient(core, RECIPIENT)
    unrelated = LocalCoreClient(core, UNRELATED)

    # Bulletin publication is deliberately not a protocol operation. Validate the
    # object with the production codec, then use the development seeding path.
    encode_frame(BULLETIN)
    seeded = bulletins.store_bulletin(
        bulletin_id=BULLETIN.bulletin_id,
        created_at=BULLETIN.created_at,
        author=BULLETIN.author,
        title=BULLETIN.title,
        body=BULLETIN.body,
    )
    assert seeded.result.name == "STORED"

    assert sender.request(MESSAGE_A) == [
        Ack(MESSAGE_A.message_id, AckStatus.STORED)
    ]
    empty_messages = [End(Operation.GET_NEW_MESSAGES, 0, 0, False)]
    assert unrelated.request(GetNewMessages(0, SYNC_LIMIT)) == empty_messages
    assert sender.request(GetNewMessages(0, SYNC_LIMIT)) == empty_messages

    first_sync = recipient.request(GetNewMessages(0, SYNC_LIMIT))
    assert len(first_sync) == 2
    message_a, first_end = first_sync
    assert isinstance(message_a, Message)
    assert message_a == Message(
        message_a.sequence,
        MESSAGE_A.message_id,
        MESSAGE_A.created_at,
        SENDER,
        RECIPIENT,
        MESSAGE_A.body,
    )
    assert first_end == End(Operation.GET_NEW_MESSAGES, 1, message_a.sequence, False)
    message_cursor = _cursor(first_sync, Operation.GET_NEW_MESSAGES)
    message_a_sequence = message_a.sequence

    assert sender.request(MESSAGE_A) == [
        Ack(MESSAGE_A.message_id, AckStatus.ALREADY_STORED)
    ]
    assert recipient.request(GetNewMessages(0, SYNC_LIMIT)) == first_sync

    # Simulate a restart while retaining only state available outside the node.
    del sender, recipient, unrelated, core, bulletins, messages, database, first_sync
    gc.collect()

    database, messages, bulletins, core = _new_node(database_path)
    sender = LocalCoreClient(core, SENDER)
    recipient = LocalCoreClient(core, RECIPIENT)

    assert recipient.request(GetNewMessages(message_cursor, SYNC_LIMIT)) == [
        End(Operation.GET_NEW_MESSAGES, 0, message_cursor, False)
    ]
    assert sender.request(MESSAGE_B) == [
        Ack(MESSAGE_B.message_id, AckStatus.STORED)
    ]
    second_sync = recipient.request(GetNewMessages(message_cursor, SYNC_LIMIT))
    assert len(second_sync) == 2
    message_b, second_end = second_sync
    assert isinstance(message_b, Message)
    assert message_b.message_id == MESSAGE_B.message_id
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
        header.sequence,
        BULLETIN.bulletin_id,
        BULLETIN.created_at,
        BULLETIN.author,
        BULLETIN.title,
    )
    assert bulletin_end == End(
        Operation.GET_NEW_BULLETINS, 1, header.sequence, False
    )
    bulletin_cursor = _cursor(bulletin_sync, Operation.GET_NEW_BULLETINS)
    assert recipient.request(GetBulletin(header.bulletin_id)) == [BULLETIN]

    assert recipient.request(GetNewMessages(latest_message_cursor, SYNC_LIMIT)) == [
        End(Operation.GET_NEW_MESSAGES, 0, latest_message_cursor, False)
    ]
    assert recipient.request(GetNewBulletins(bulletin_cursor, SYNC_LIMIT)) == [
        End(Operation.GET_NEW_BULLETINS, 0, bulletin_cursor, False)
    ]
