#!/usr/bin/env python3
"""Run the M4.3 conflicting reuse of a stored message identifier."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from client_sim import LocalCoreClient  # noqa: E402
from openqsp.protocol import (  # noqa: E402
    Ack,
    AckStatus,
    End,
    GetNewMessages,
    Message,
    Operation,
    ProtocolObject,
    SendMessage,
)
from openqsp.server import ServerCore  # noqa: E402
from openqsp.storage import Database, MessageStore  # noqa: E402


SENDER = "EA3AAA"
RECIPIENT = "EA3BBB"
MESSAGE_ID = 0x4D340003
CREATED_AT = 1_786_200_002
ORIGINAL_BODY = "M4.3 original message"
CONFLICTING_BODY = "M4.3 conflicting message"


@dataclass(frozen=True)
class ScenarioResult:
    """Decoded production responses observed during the M4.3 scenario."""

    original_send: list[ProtocolObject]
    conflicting_send: list[ProtocolObject]
    recipient_mailbox: list[ProtocolObject]
    recipient_after_cursor: list[ProtocolObject]


def run_scenario(database_path: str | Path) -> ScenarioResult:
    """Reuse one message ID with a changed body through public Core interfaces."""
    database = Database(database_path)
    database.initialize()
    core = ServerCore(message_store=MessageStore(database))

    sender = LocalCoreClient(core, SENDER)
    recipient = LocalCoreClient(core, RECIPIENT)

    original = SendMessage(MESSAGE_ID, CREATED_AT, RECIPIENT, ORIGINAL_BODY)
    conflict = SendMessage(MESSAGE_ID, CREATED_AT, RECIPIENT, CONFLICTING_BODY)
    original_send = sender.request(original)
    if original_send != [Ack(MESSAGE_ID, AckStatus.STORED)]:
        raise AssertionError(f"expected first ACK STORED, got {original_send!r}")

    conflicting_send = sender.request(conflict)
    if conflicting_send != [Ack(MESSAGE_ID, AckStatus.CONFLICT)]:
        raise AssertionError(
            f"expected changed-body ACK CONFLICT, got {conflicting_send!r}"
        )

    recipient_mailbox = recipient.request(GetNewMessages(0, 20))
    expected_message = Message(
        1, MESSAGE_ID, CREATED_AT, SENDER, RECIPIENT, ORIGINAL_BODY
    )
    expected_end = End(Operation.GET_NEW_MESSAGES, 1, 1, False)
    if recipient_mailbox != [expected_message, expected_end]:
        raise AssertionError("conflict changed or duplicated the original message")

    # An empty read from the only assigned sequence proves through the public
    # Core API that the rejected attempt neither created an object nor used 2.
    recipient_after_cursor = recipient.request(
        GetNewMessages(expected_end.next_since, 20)
    )
    expected_empty = [End(Operation.GET_NEW_MESSAGES, 0, 1, False)]
    if recipient_after_cursor != expected_empty:
        raise AssertionError("conflict created a duplicate or consumed sequence 2")

    return ScenarioResult(
        original_send,
        conflicting_send,
        recipient_mailbox,
        recipient_after_cursor,
    )


def _describe(response: ProtocolObject) -> str:
    if isinstance(response, Ack):
        return f"ACK id={response.object_id} status={response.status.name}"
    if isinstance(response, Message):
        return (
            f"MESSAGE sequence={response.sequence} id={response.message_id} "
            f"author={response.author} recipient={response.recipient} "
            f"body={response.body!r}"
        )
    if isinstance(response, End):
        return (
            f"END returned={response.returned_count} "
            f"next_since={response.next_since} has_more={response.has_more}"
        )
    return repr(response)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1:
        print("usage: message_id_conflict.py DATABASE", file=sys.stderr)
        return 2

    result = run_scenario(argv[0])
    for label, responses in (
        (SENDER + " original send", result.original_send),
        (SENDER + " changed-body reuse", result.conflicting_send),
        (RECIPIENT + " mailbox", result.recipient_mailbox),
        (RECIPIENT + " mailbox after cursor", result.recipient_after_cursor),
    ):
        print(label)
        for response in responses:
            print(f"  {_describe(response)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
