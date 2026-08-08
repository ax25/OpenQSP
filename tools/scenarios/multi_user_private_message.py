#!/usr/bin/env python3
"""Run the M4.1 private-message workflow through the real local node stack."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from scenario_environment import (  # noqa: E402
    LocalScenarioEnvironment,
    ScenarioEnvironment,
)
from openqsp.protocol import (  # noqa: E402
    Stored,
    End,
    GetNewMessages,
    Message,
    ProtocolObject,
    SendMessage,
)


SENDER = "EA3AAA"
RECIPIENT = "EA3BBB"
THIRD_USER = "EA3CCC"
MESSAGE_ID = 0x4D340001
CREATED_AT = 1_786_200_000
BODY = "M4.1 private message"


@dataclass(frozen=True)
class ScenarioResult:
    """Decoded production responses observed during the M4.1 scenario."""

    send: list[ProtocolObject]
    recipient_mailbox: list[ProtocolObject]
    sender_mailbox: list[ProtocolObject]
    third_user_mailbox: list[ProtocolObject]


def run_scenario(env: ScenarioEnvironment) -> ScenarioResult:
    """Exchange one private message using only public client/Core interfaces."""
    sender = env.client(SENDER)
    recipient = env.client(RECIPIENT)
    third_user = env.client(THIRD_USER)

    send = sender.request(SendMessage(CREATED_AT, RECIPIENT, BODY))
    recipient_mailbox = recipient.request(GetNewMessages(0, 20))
    sender_mailbox = sender.request(GetNewMessages(0, 20))
    third_user_mailbox = third_user.request(GetNewMessages(0, 20))
    return ScenarioResult(send, recipient_mailbox, sender_mailbox, third_user_mailbox)


def _describe(response: ProtocolObject) -> str:
    if isinstance(response, Stored):
        return f"ACK id={response.sequence} status={response.status.name}"
    if isinstance(response, Message):
        return (
            f"MESSAGE sequence={response.sequence} id={response.sequence} "
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
        print("usage: multi_user_private_message.py DATABASE", file=sys.stderr)
        return 2

    result = run_scenario(LocalScenarioEnvironment(argv[0]))
    for label, responses in (
        (SENDER + " send", result.send),
        (RECIPIENT + " mailbox", result.recipient_mailbox),
        (SENDER + " mailbox", result.sender_mailbox),
        (THIRD_USER + " mailbox", result.third_user_mailbox),
    ):
        print(label)
        for response in responses:
            print(f"  {_describe(response)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
