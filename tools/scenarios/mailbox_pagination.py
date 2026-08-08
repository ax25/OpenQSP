"""Run the M4.6 private-mailbox pagination and has_more scenario."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import sys

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))
from client_sim import completed_cursor
from scenario_environment import (
    LocalScenarioEnvironment,
    ScenarioClient,
    ScenarioEnvironment,
)
from openqsp.protocol import (
    End,
    GetNewMessages,
    Message,
    Operation,
    ProtocolObject,
    SendMessage,
    Stored,
)

RECIPIENT = "EA3BBB"
PAGE_SIZE = 2
MESSAGE_A = SendMessage(1786500001, RECIPIENT, "A")
OTHER_MESSAGE_X = SendMessage(1786500002, "EA3ZZZ", "X")
MESSAGE_B = SendMessage(1786500003, RECIPIENT, "B")
MESSAGE_C = SendMessage(1786500004, RECIPIENT, "C")
OTHER_MESSAGE_Y = SendMessage(1786500005, "EA3YYY", "Y")
MESSAGE_D = SendMessage(1786500006, RECIPIENT, "D")
MESSAGE_E = SendMessage(1786500007, RECIPIENT, "E")
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
    expected = [Stored()]
    if responses != expected:
        raise AssertionError(f"expected STORED, got {responses!r}")
    return responses


def _completed_mailbox_cursor(responses: list[ProtocolObject]) -> int:
    cursor = completed_cursor(responses, Operation.GET_NEW_MESSAGES)
    if cursor is None:
        raise AssertionError("mailbox page did not end with a valid END")
    return cursor


def run_scenario(env: ScenarioEnvironment) -> ScenarioResult:
    """Retrieve EA3BBB page by page using only each preceding END cursor."""
    clients = {
        callsign: env.client(callsign) for callsign in ("EA3AAA", "EA3CCC", "EA3DDD")
    }
    sends = [_send(clients[author], message) for author, message in SUBMISSIONS]
    recipient = env.client(RECIPIENT)
    request_since = [0]
    pages = [recipient.request(GetNewMessages(request_since[0], PAGE_SIZE))]
    for _ in range(3):
        request_since.append(_completed_mailbox_cursor(pages[-1]))
        pages.append(recipient.request(GetNewMessages(request_since[-1], PAGE_SIZE)))
    return ScenarioResult(sends, pages, request_since)


def _describe(response: ProtocolObject) -> str:
    if isinstance(response, Message):
        return f"MESSAGE sequence={response.sequence} author={response.author} recipient={response.recipient} body={response.body!r}"
    if isinstance(response, End):
        return f"END returned={response.returned_count} next_since={response.next_since} has_more={str(response.has_more).lower()}"
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
