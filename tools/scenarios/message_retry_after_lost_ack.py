#!/usr/bin/env python3
"""Run the M4.2 identical-message retry after a lost acknowledgement."""

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
MESSAGE_ID = 0x4D340002
CREATED_AT = 1_786_200_001
BODY = "M4.2 retry after lost acknowledgement"


@dataclass(frozen=True)
class ScenarioResult:
    """Decoded production responses observed during the M4.2 scenario."""

    first_send: list[ProtocolObject]
    retry_send: list[ProtocolObject]
    recipient_mailbox: list[ProtocolObject]
    recipient_after_cursor: list[ProtocolObject]


def run_scenario(database_path: str | Path) -> ScenarioResult:
    """Retry one unchanged request and verify idempotency via public interfaces."""
    database = Database(database_path)
    database.initialize()
    core = ServerCore(message_store=MessageStore(database))

    sender = LocalCoreClient(core, SENDER)
    recipient = LocalCoreClient(core, RECIPIENT)
    request = SendMessage(MESSAGE_ID, CREATED_AT, RECIPIENT, BODY)

    # The node processes and returns the first ACK normally.  The simulated
    # client verifies it here but deliberately does not use it to alter the
    # retry: the exact same SendMessage is submitted through the full stack.
    first_send = sender.request(request)
    expected_first_ack = [Ack(MESSAGE_ID, AckStatus.STORED)]
    if first_send != expected_first_ack:
        raise AssertionError(f"expected first ACK STORED, got {first_send!r}")

    retry_send = sender.request(request)
    expected_retry_ack = [Ack(MESSAGE_ID, AckStatus.ALREADY_STORED)]
    if retry_send != expected_retry_ack:
        raise AssertionError(f"expected retry ACK ALREADY_STORED, got {retry_send!r}")

    recipient_mailbox = recipient.request(GetNewMessages(0, 20))
    if len(recipient_mailbox) != 2:
        raise AssertionError("retry must yield exactly one MESSAGE followed by END")
    message, end = recipient_mailbox
    if not isinstance(message, Message) or not isinstance(end, End):
        raise AssertionError("retry must yield exactly one MESSAGE followed by END")
    if end != End(Operation.GET_NEW_MESSAGES, 1, message.sequence, False):
        raise AssertionError("mailbox END must describe the single stored message")

    # An empty follow-up from the returned cursor publicly demonstrates both
    # that there is no duplicate and that the retry consumed no new sequence.
    recipient_after_cursor = recipient.request(
        GetNewMessages(end.next_since, 20)
    )
    expected_empty_end = [
        End(Operation.GET_NEW_MESSAGES, 0, end.next_since, False)
    ]
    if recipient_after_cursor != expected_empty_end:
        raise AssertionError("retry created a duplicate or advanced the sequence")

    return ScenarioResult(
        first_send, retry_send, recipient_mailbox, recipient_after_cursor
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
        print("usage: message_retry_after_lost_ack.py DATABASE", file=sys.stderr)
        return 2

    result = run_scenario(argv[0])
    for label, responses in (
        (SENDER + " first send (ACK intentionally ignored)", result.first_send),
        (SENDER + " identical retry", result.retry_send),
        (RECIPIENT + " mailbox", result.recipient_mailbox),
        (RECIPIENT + " mailbox after cursor", result.recipient_after_cursor),
    ):
        print(label)
        for response in responses:
            print(f"  {_describe(response)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
