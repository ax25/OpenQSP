#!/usr/bin/env python3
"""Emulate one OpenQSP user against a persistent local ServerCore."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Make the production package importable from an uninstalled checkout.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVER_SRC = REPOSITORY_ROOT / "server" / "src"
if str(SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(SERVER_SRC))

from openqsp.protocol import (  # noqa: E402
    Ack,
    Bulletin,
    BulletinHeader,
    End,
    Error,
    GetBulletin,
    GetNewBulletins,
    GetNewMessages,
    Message,
    Operation,
    ProtocolObject,
    SendMessage,
    decode_frame,
    encode_frame,
)
from openqsp.protocol.errors import ProtocolError  # noqa: E402
from openqsp.server import ServerCore  # noqa: E402
from openqsp.storage import BulletinStore, Database, MessageStore  # noqa: E402


def parse_integer(value: str) -> int:
    """Parse decimal and 0x-prefixed integer arguments."""
    try:
        return int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer: {value!r}") from exc


def decode_responses(frames: list[bytes]) -> list[ProtocolObject]:
    """Decode server output solely through the production codec."""
    return [decode_frame(frame) for frame in frames]


def completed_cursor(
    responses: list[ProtocolObject], request_operation: Operation
) -> int | None:
    """Return a cursor only from the terminating END of a complete response.

    A caller processing a partial frame list therefore cannot accidentally
    advance from the sequence carried by an item frame.
    """
    if not responses or not isinstance(responses[-1], End):
        return None
    end = responses[-1]
    if end.request_operation != request_operation:
        return None
    return end.next_since


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="persistent SQLite DB")
    parser.add_argument(
        "--callsign",
        required=True,
        help="authenticated test callsign (passed unchanged to ServerCore)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    send = commands.add_parser("send-message", help="submit a private message")
    send.add_argument("--to", required=True, dest="recipient")
    send.add_argument("--id", required=True, type=parse_integer, dest="message_id")
    send.add_argument("--timestamp", required=True, type=parse_integer)
    send.add_argument("--body", required=True)

    for name in ("get-new-messages", "get-new-bulletins"):
        retrieval = commands.add_parser(name)
        retrieval.add_argument("--since", required=True, type=parse_integer)
        retrieval.add_argument("--max", required=True, type=parse_integer)

    bulletin = commands.add_parser("get-bulletin")
    bulletin.add_argument("--id", required=True, type=parse_integer, dest="bulletin_id")

    seed = commands.add_parser(
        "seed-bulletin",
        help="development-only node setup (not an OpenQSP client operation)",
    )
    seed.add_argument("--id", required=True, type=parse_integer, dest="bulletin_id")
    seed.add_argument("--timestamp", required=True, type=parse_integer)
    seed.add_argument("--title", required=True)
    seed.add_argument("--body", required=True)
    return parser


def _request(args: argparse.Namespace) -> ProtocolObject:
    if args.command == "send-message":
        return SendMessage(args.message_id, args.timestamp, args.recipient, args.body)
    if args.command == "get-new-messages":
        return GetNewMessages(args.since, args.max)
    if args.command == "get-new-bulletins":
        return GetNewBulletins(args.since, args.max)
    if args.command == "get-bulletin":
        return GetBulletin(args.bulletin_id)
    raise ValueError(f"not a client operation: {args.command}")


def _print_response(response: ProtocolObject) -> None:
    if isinstance(response, Ack):
        print("ACK")
        print(f"  object_id: {response.object_id}")
        print(f"  status: {response.status.name}")
    elif isinstance(response, Message):
        print("MESSAGE")
        print(f"  sequence: {response.sequence}")
        print(f"  message_id: {response.message_id}")
        print(f"  created_at: {response.created_at}")
        print(f"  author: {response.author}")
        print(f"  recipient: {response.recipient}")
        print(f"  body: {response.body}")
    elif isinstance(response, BulletinHeader):
        print("BULLETIN_HEADER")
        print(f"  sequence: {response.sequence}")
        print(f"  bulletin_id: {response.bulletin_id}")
        print(f"  created_at: {response.created_at}")
        print(f"  author: {response.author}")
        print(f"  title: {response.title}")
    elif isinstance(response, Bulletin):
        print("BULLETIN")
        print(f"  bulletin_id: {response.bulletin_id}")
        print(f"  created_at: {response.created_at}")
        print(f"  author: {response.author}")
        print(f"  title: {response.title}")
        print(f"  body: {response.body}")
    elif isinstance(response, End):
        print("END")
        print(f"  returned: {response.returned_count}")
        print(f"  next_since: {response.next_since}")
        print(f"  has_more: {str(response.has_more).lower()}")
    elif isinstance(response, Error):
        print("ERROR")
        print(f"  operation: {getattr(response.request_operation, 'name', 0)}")
        print(f"  code: {response.error_code.name}")
        print(f"  detail: {response.detail}")
    else:  # pragma: no cover - all v0.1 response models are handled above.
        raise TypeError(f"unexpected response: {type(response).__name__}")
    print()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    database = Database(args.db)
    database.initialize()
    bulletin_store = BulletinStore(database)

    try:
        if args.command == "seed-bulletin":
            # This is node/test setup, deliberately separated from client
            # operations. Encoding validates fields before direct store setup.
            bulletin = Bulletin(
                args.bulletin_id,
                args.timestamp,
                args.callsign,
                args.title,
                args.body,
            )
            encode_frame(bulletin)
            outcome = bulletin_store.store_bulletin(
                bulletin_id=bulletin.bulletin_id,
                created_at=bulletin.created_at,
                author=bulletin.author,
                title=bulletin.title,
                body=bulletin.body,
            )
            print("DEVELOPMENT SEED")
            print(f"  object_id: {args.bulletin_id}")
            print(f"  status: {outcome.result.name}")
            return 0

        core = ServerCore(
            message_store=MessageStore(database), bulletin_store=bulletin_store
        )
        request_frame = encode_frame(_request(args))
        responses = decode_responses(core.handle_frame(args.callsign, request_frame))
    except (ProtocolError, TypeError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    for response in responses:
        _print_response(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
