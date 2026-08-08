"""Run the M4.5 empty private-mailbox synchronization scenario."""

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

EMPTY_RECIPIENT = "EA3BBB"
SYNCED_RECIPIENT = "EA3CCC"
OTHER_RECIPIENT = "EA3ZZZ"
SYNC_LIMIT = 20
SYNCED_MESSAGE = SendMessage(1786400001, SYNCED_RECIPIENT, "M4.5 synchronized message")
OTHER_MESSAGE = SendMessage(1786400002, OTHER_RECIPIENT, "M4.5 unrelated activity")


@dataclass(frozen=True)
class ScenarioResult:
    """Decoded responses and the completed cursor used by M4.5."""

    initial_empty_sync: list[ProtocolObject]
    synced_send: list[ProtocolObject]
    initial_sync: list[ProtocolObject]
    cursor: int
    other_send: list[ProtocolObject]
    repeated_empty_sync: list[ProtocolObject]


def _send(client: ScenarioClient, message: SendMessage) -> list[ProtocolObject]:
    responses = client.request(message)
    expected = [Stored()]
    if responses != expected:
        raise AssertionError(f"expected STORED, got {responses!r}")
    return responses


def run_scenario(env: ScenarioEnvironment) -> ScenarioResult:
    """Exercise empty synchronization through the public local Core stack."""
    sender = env.client("EA3AAA")
    empty_recipient = env.client(EMPTY_RECIPIENT)
    synced_recipient = env.client(SYNCED_RECIPIENT)
    initial_empty_sync = empty_recipient.request(GetNewMessages(0, SYNC_LIMIT))
    synced_send = _send(sender, SYNCED_MESSAGE)
    initial_sync = synced_recipient.request(GetNewMessages(0, SYNC_LIMIT))
    cursor = completed_cursor(initial_sync, Operation.GET_NEW_MESSAGES)
    if cursor is None:
        raise AssertionError("initial synchronization did not end with a valid END")
    other_send = _send(sender, OTHER_MESSAGE)
    repeated_empty_sync = synced_recipient.request(GetNewMessages(cursor, SYNC_LIMIT))
    return ScenarioResult(
        initial_empty_sync,
        synced_send,
        initial_sync,
        cursor,
        other_send,
        repeated_empty_sync,
    )


def _describe(response: ProtocolObject) -> str:
    if isinstance(response, Stored):
        return "STORED"
    if isinstance(response, Message):
        return f"MESSAGE sequence={response.sequence} author={response.author} recipient={response.recipient} body={response.body!r}"
    if isinstance(response, End):
        return f"END returned={response.returned_count} next_since={response.next_since} has_more={str(response.has_more).lower()}"
    return repr(response)


def _print_responses(label: str, responses: list[ProtocolObject]) -> None:
    print(label)
    for response in responses:
        print(f"  {_describe(response)}")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1:
        print("usage: empty_mailbox_sync.py DATABASE", file=sys.stderr)
        return 2
    result = run_scenario(LocalScenarioEnvironment(argv[0]))
    _print_responses("EA3BBB initial empty sync", result.initial_empty_sync)
    _print_responses("EA3CCC message setup", result.synced_send)
    _print_responses("EA3CCC initial sync", result.initial_sync)
    print(f"  completed cursor={result.cursor}")
    _print_responses("EA3ZZZ unrelated mailbox activity", result.other_send)
    _print_responses(
        f"EA3CCC repeated empty sync since={result.cursor}", result.repeated_empty_sync
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
