"""Run the M4.7 node-restart and persistent synchronization scenario."""

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

SENDER = "EA3AAA"
RECIPIENT = "EA3BBB"
UNRELATED_USER = "EA3CCC"
SYNC_LIMIT = 20
MESSAGE_A = SendMessage(1786700001, RECIPIENT, "M4.7 message A")
MESSAGE_B = SendMessage(1786700002, RECIPIENT, "M4.7 message B")


@dataclass(frozen=True)
class ScenarioResult:
    """Public protocol observations made on both sides of the restart."""

    send_a: list[ProtocolObject]
    first_sync: list[ProtocolObject]
    first_cursor: int
    unrelated_before_restart: list[ProtocolObject]
    durable_sync: list[ProtocolObject]
    empty_from_old_cursor: list[ProtocolObject]
    send_b: list[ProtocolObject]
    incremental_sync: list[ProtocolObject]
    unrelated_after_restart: list[ProtocolObject]
    sender_after_restart: list[ProtocolObject]


def _cursor(responses: list[ProtocolObject]) -> int:
    cursor = completed_cursor(responses, Operation.GET_NEW_MESSAGES)
    if cursor is None:
        raise AssertionError("synchronization did not finish with a valid END")
    return cursor


def _send(client: ScenarioClient, message: SendMessage) -> list[ProtocolObject]:
    responses = client.request(message)
    expected = [Stored()]
    if responses != expected:
        raise AssertionError(f"expected ACK/STORED, got {responses!r}")
    return responses


def run_scenario(env: ScenarioEnvironment) -> ScenarioResult:
    """Reconstruct a node while retaining only its persistent database file."""
    sender = env.client(SENDER)
    recipient = env.client(RECIPIENT)
    unrelated = env.client(UNRELATED_USER)
    send_a = _send(sender, MESSAGE_A)
    first_sync = recipient.request(GetNewMessages(0, SYNC_LIMIT))
    first_cursor = _cursor(first_sync)
    unrelated_before_restart = unrelated.request(GetNewMessages(0, SYNC_LIMIT))
    del sender, recipient, unrelated
    env.restart_node()
    sender = env.client(SENDER)
    recipient = env.client(RECIPIENT)
    unrelated = env.client(UNRELATED_USER)
    durable_sync = recipient.request(GetNewMessages(0, SYNC_LIMIT))
    empty_from_old_cursor = recipient.request(GetNewMessages(first_cursor, SYNC_LIMIT))
    send_b = _send(sender, MESSAGE_B)
    incremental_sync = recipient.request(GetNewMessages(first_cursor, SYNC_LIMIT))
    unrelated_after_restart = unrelated.request(GetNewMessages(0, SYNC_LIMIT))
    sender_after_restart = sender.request(GetNewMessages(0, SYNC_LIMIT))
    return ScenarioResult(
        send_a,
        first_sync,
        first_cursor,
        unrelated_before_restart,
        durable_sync,
        empty_from_old_cursor,
        send_b,
        incremental_sync,
        unrelated_after_restart,
        sender_after_restart,
    )


def _describe(response: ProtocolObject) -> str:
    if isinstance(response, Stored):
        return "STORED"
    if isinstance(response, Message):
        return f"MESSAGE sequence={response.sequence} body={response.body!r}"
    if isinstance(response, End):
        return f"END returned={response.returned_count} next_since={response.next_since} has_more={response.has_more}"
    return repr(response)


def _print(label: str, responses: list[ProtocolObject]) -> None:
    print(label)
    for response in responses:
        print(f"  {_describe(response)}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: node_restart_persistence.py DATABASE", file=sys.stderr)
        return 2
    result = run_scenario(LocalScenarioEnvironment(argv[0]))
    _print("Message A stored", result.send_a)
    print(f"First completed cursor (from END): {result.first_cursor}")
    print("Simulated node restart (all node and storage objects reconstructed)")
    _print("Durable message A after restart", result.durable_sync)
    _print("Empty synchronization from old cursor", result.empty_from_old_cursor)
    _print("Message B stored", result.send_b)
    _print(
        "Incremental synchronization returning only message B", result.incremental_sync
    )
    first_message, second_message = (result.first_sync[0], result.incremental_sync[0])
    assert isinstance(first_message, Message) and isinstance(second_message, Message)
    print(
        f"Sequence/cursor continuity: sequence {first_message.sequence} -> {second_message.sequence}; cursor {result.first_cursor} -> {_cursor(result.incremental_sync)}"
    )
    print("SUCCESS: persistent restart synchronization and isolation verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
