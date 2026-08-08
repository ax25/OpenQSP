#!/usr/bin/env python3
"""Run the M4.4 incremental private-mailbox synchronization scenario."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from client_sim import LocalCoreClient, completed_cursor  # noqa: E402
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


RECIPIENT = "EA3BBB"
OTHER_RECIPIENT = "EA3ZZZ"
SYNC_LIMIT = 20

MESSAGE_A = SendMessage(0x4D340401, 1_786_300_001, RECIPIENT, "M4.4 message A")
OTHER_MESSAGE = SendMessage(
    0x4D340402, 1_786_300_002, OTHER_RECIPIENT, "M4.4 isolated message"
)
MESSAGE_B = SendMessage(0x4D340403, 1_786_300_003, RECIPIENT, "M4.4 message B")
MESSAGE_C = SendMessage(0x4D340404, 1_786_300_004, RECIPIENT, "M4.4 message C")
MESSAGE_D = SendMessage(0x4D340405, 1_786_300_005, RECIPIENT, "M4.4 message D")


@dataclass(frozen=True)
class ScenarioResult:
    """Decoded production responses and END-derived cursors from M4.4."""

    initial_sends: list[list[ProtocolObject]]
    first_sync: list[ProtocolObject]
    first_cursor: int
    later_sends: list[list[ProtocolObject]]
    second_sync: list[ProtocolObject]
    second_cursor: int
    third_sync: list[ProtocolObject]


def _send(
    clients: dict[str, LocalCoreClient], author: str, message: SendMessage
) -> list[ProtocolObject]:
    responses = clients[author].request(message)
    expected = [Ack(message.message_id, AckStatus.STORED)]
    if responses != expected:
        raise AssertionError(f"expected ACK STORED for {message.message_id}, got {responses!r}")
    return responses


def _cursor(responses: list[ProtocolObject]) -> int:
    cursor = completed_cursor(responses, Operation.GET_NEW_MESSAGES)
    if cursor is None:
        raise AssertionError("mailbox synchronization did not end with a valid END")
    return cursor


def run_scenario(database_path: str | Path) -> ScenarioResult:
    """Synchronize one mailbox three times using only public Core interfaces."""
    database = Database(database_path)
    database.initialize()
    core = ServerCore(message_store=MessageStore(database))

    authors = ("EA3AAA", "EA3CCC", "EA3DDD")
    clients = {callsign: LocalCoreClient(core, callsign) for callsign in authors}
    recipient = LocalCoreClient(core, RECIPIENT)

    # The other recipient's message deliberately creates a gap in EA3BBB's
    # visible global message sequences (A=1, isolated=2, B=3).
    initial_sends = [
        _send(clients, "EA3AAA", MESSAGE_A),
        _send(clients, "EA3AAA", OTHER_MESSAGE),
        _send(clients, "EA3CCC", MESSAGE_B),
    ]
    first_sync = recipient.request(GetNewMessages(0, SYNC_LIMIT))
    first_cursor = _cursor(first_sync)

    later_sends = [
        _send(clients, "EA3AAA", MESSAGE_C),
        _send(clients, "EA3DDD", MESSAGE_D),
    ]
    # Both follow-up cursors come from completed END responses, as a real
    # client would persist them; no item sequence or scenario constant is used.
    second_sync = recipient.request(GetNewMessages(first_cursor, SYNC_LIMIT))
    second_cursor = _cursor(second_sync)
    third_sync = recipient.request(GetNewMessages(second_cursor, SYNC_LIMIT))

    return ScenarioResult(
        initial_sends,
        first_sync,
        first_cursor,
        later_sends,
        second_sync,
        second_cursor,
        third_sync,
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


def _print_responses(label: str, responses: list[ProtocolObject]) -> None:
    print(label)
    for response in responses:
        print(f"  {_describe(response)}")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1:
        print("usage: incremental_mailbox_sync.py DATABASE", file=sys.stderr)
        return 2

    result = run_scenario(argv[0])
    print("Initial messages sent: A and B to EA3BBB; isolated message to EA3ZZZ")
    for responses in result.initial_sends:
        _print_responses("send", responses)
    _print_responses("First sync: EA3BBB since=0", result.first_sync)
    print(f"Cursor obtained from first END: {result.first_cursor}\n")
    print("New messages sent: C and D to EA3BBB")
    for responses in result.later_sends:
        _print_responses("send", responses)
    _print_responses(
        f"Second sync: EA3BBB since={result.first_cursor}", result.second_sync
    )
    print(f"Cursor obtained from second END: {result.second_cursor}\n")
    _print_responses(
        f"Third sync (empty): EA3BBB since={result.second_cursor}",
        result.third_sync,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
