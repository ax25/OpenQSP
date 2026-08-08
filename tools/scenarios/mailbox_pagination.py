#!/usr/bin/env python3
"""Run the M4.6 private-mailbox pagination and has_more scenario."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from client_sim import completed_cursor  # noqa: E402
from scenario_environment import (  # noqa: E402
    LocalScenarioEnvironment,
    ScenarioClient,
    ScenarioEnvironment,
)
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


RECIPIENT = "EA3BBB"
PAGE_SIZE = 2

MESSAGE_A = SendMessage(0x4D340601, 1_786_500_001, RECIPIENT, "A")
OTHER_MESSAGE_X = SendMessage(0x4D340602, 1_786_500_002, "EA3ZZZ", "X")
MESSAGE_B = SendMessage(0x4D340603, 1_786_500_003, RECIPIENT, "B")
MESSAGE_C = SendMessage(0x4D340604, 1_786_500_004, RECIPIENT, "C")
OTHER_MESSAGE_Y = SendMessage(0x4D340605, 1_786_500_005, "EA3YYY", "Y")
MESSAGE_D = SendMessage(0x4D340606, 1_786_500_006, RECIPIENT, "D")
MESSAGE_E = SendMessage(0x4D340607, 1_786_500_007, RECIPIENT, "E")

SUBMISSIONS = (
    ("EA3AAA", MESSAGE_A),
    ("EA3AAA", OTHER_MESSAGE_X),
    ("EA3CCC", MESSAGE_B),
    ("EA3AAA", MESSAGE_C),
    ("EA3DDD", OTHER_MESSAGE_Y),
    ("EA3DDD", MESSAGE_D),
    ("EA3AAA", MESSAGE_E),
)
MAILBOX_MESSAGES = (MESSAGE_A, MESSAGE_B, MESSAGE_C, MESSAGE_D, MESSAGE_E)


@dataclass(frozen=True)
class ScenarioResult:
    """Decoded production responses and END-derived cursors from M4.6."""

    sends: list[list[ProtocolObject]]
    pages: list[list[ProtocolObject]]
    request_since: list[int]


def _send(client: ScenarioClient, message: SendMessage) -> list[ProtocolObject]:
    responses = client.request(message)
    expected = [Ack(message.message_id, AckStatus.STORED)]
    if responses != expected:
        raise AssertionError(
            f"expected ACK STORED for {message.message_id}, got {responses!r}"
        )
    return responses


def _completed_mailbox_cursor(responses: list[ProtocolObject]) -> int:
    cursor = completed_cursor(responses, Operation.GET_NEW_MESSAGES)
    if cursor is None:
        raise AssertionError("mailbox page did not end with a valid END")
    return cursor


def run_scenario(env: ScenarioEnvironment) -> ScenarioResult:
    """Retrieve EA3BBB page by page using only each preceding END cursor."""
    clients = {
        callsign: env.client(callsign)
        for callsign in ("EA3AAA", "EA3CCC", "EA3DDD")
    }
    sends = [
        _send(clients[author], message) for author, message in SUBMISSIONS
    ]

    recipient = env.client(RECIPIENT)
    request_since = [0]
    pages = [recipient.request(GetNewMessages(request_since[0], PAGE_SIZE))]

    # Every subsequent request depends exclusively on completed_cursor(),
    # never on an item sequence or knowledge of storage internals.
    for _ in range(3):
        request_since.append(_completed_mailbox_cursor(pages[-1]))
        pages.append(
            recipient.request(GetNewMessages(request_since[-1], PAGE_SIZE))
        )

    return ScenarioResult(sends, pages, request_since)


def _describe(response: ProtocolObject) -> str:
    if isinstance(response, Message):
        return (
            f"MESSAGE sequence={response.sequence} id={response.message_id} "
            f"author={response.author} recipient={response.recipient} "
            f"body={response.body!r}"
        )
    if isinstance(response, End):
        return (
            f"END returned={response.returned_count} "
            f"next_since={response.next_since} "
            f"has_more={str(response.has_more).lower()}"
        )
    return repr(response)


def _print_page(label: str, since: int, responses: list[ProtocolObject]) -> None:
    print(f"{label} since={since}")
    for response in responses:
        print(f"  {_describe(response)}")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1:
        print("usage: mailbox_pagination.py DATABASE", file=sys.stderr)
        return 2

    result = run_scenario(LocalScenarioEnvironment(argv[0]))
    print("Stored five EA3BBB messages and two interleaved mailbox messages")
    for index, (page, since) in enumerate(
        zip(result.pages, result.request_since, strict=True), start=1
    ):
        if index < 3:
            label = f"Page {index}"
        elif index == 3:
            label = "Final page"
        else:
            label = "Empty follow-up"
        _print_page(label, since, page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
