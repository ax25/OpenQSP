"""Interactive terminal interface for the OpenQSP reference TCP client."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime
import shlex
import getpass

from openqsp.client.tcp import ClientError, OpenQSPClient
from openqsp.protocol import (
    Bulletin,
    BulletinHeader,
    Capability,
    Message,
    ProtocolObject,
)

COMMAND_HELP = """Commands:
  help                         show this help
  status                       show connection and identity
  services                     show operations in protocol version 0.1
  messages                     retrieve all private messages from cursor 0
  new                          retrieve private messages after the last cursor
  send <CALLSIGN> <text>       send a title-less private message
  bulletins                    retrieve new bulletin headers
  read <sequence>              retrieve a complete bulletin
  quit                         disconnect and exit"""


def _format_time(value: int) -> str:
    return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")


def format_object(obj: ProtocolObject) -> str:
    if isinstance(obj, Message):
        return f"[{obj.sequence}] {_format_time(obj.created_at)} {obj.author} -> {obj.recipient}: {obj.body}"
    if isinstance(obj, BulletinHeader):
        return (
            f"[{obj.sequence}] {_format_time(obj.created_at)} {obj.author}: {obj.title}"
        )
    if isinstance(obj, Bulletin):
        return f"[{obj.sequence}] {obj.title}\nFrom: {obj.author} ({_format_time(obj.created_at)})\n{obj.body}"
    return str(obj)


class CommandSession:
    """CLI command state, separated from terminal input for easy reuse/testing."""

    def __init__(self, client: OpenQSPClient) -> None:
        self.client = client
        self.message_cursor = 0
        self.bulletin_cursor = 0

    def execute(self, line: str) -> tuple[bool, str]:
        try:
            parts = shlex.split(line)
        except ValueError as error:
            return True, f"Error: {error}"
        if not parts:
            return True, ""
        command, args = parts[0].lower(), parts[1:]
        if command == "help" and not args:
            return True, COMMAND_HELP
        if command == "quit" and not args:
            return False, ""
        if command == "status" and not args:
            host, port = self.client.endpoint
            return (
                True,
                f"Connected: {'yes' if self.client.connected else 'no'}\nAuthenticated: {self.client.callsign or 'no'}\nServer: {host}:{port}",
            )
        if command == "services" and not args:
            discovered = self.client.get_capabilities()
            names = [
                capability.name
                for capability in Capability
                if discovered.capabilities & capability
            ]
            return (
                True,
                f"Protocol: {discovered.protocol_version}\nCapabilities: {', '.join(names) or 'none'}",
            )
        if command in ("messages", "new") and not args:
            since = 0 if command == "messages" else self.message_cursor
            messages, end = self.client.get_messages(since)
            self.message_cursor = end.next_since
            return True, "\n".join(map(format_object, messages)) or "No messages."
        if command == "send" and len(args) >= 2:
            self.client.send_message(args[0].upper(), " ".join(args[1:]))
            return True, "Message stored."
        if command == "bulletins" and not args:
            headers, end = self.client.get_bulletins(self.bulletin_cursor)
            self.bulletin_cursor = end.next_since
            return True, "\n".join(map(format_object, headers)) or "No new bulletins."
        if command == "read" and len(args) == 1:
            try:
                sequence = int(args[0], 0)
            except ValueError:
                return True, "Usage: read <sequence>"
            return True, format_object(self.client.get_bulletin(sequence))
        if command in {
            "help",
            "quit",
            "status",
            "services",
            "messages",
            "new",
            "send",
            "bulletins",
            "read",
        }:
            usage = next(
                line.strip()
                for line in COMMAND_HELP.splitlines()
                if line.strip().startswith(command)
            )
            return True, f"Usage: {usage}"
        return True, f"Unknown command: {parts[0]}. Type 'help' for commands."


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8023)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--callsign")
    parser.add_argument("--password", help="password (omit to prompt securely)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    def show_event(obj: ProtocolObject) -> None:
        label = "NEW MESSAGE" if isinstance(obj, Message) else "SERVER EVENT"
        print(f"\n[{label}]\n{format_object(obj)}\n\nopenqsp> ", end="", flush=True)

    client = OpenQSPClient(args.host, args.port, event_handler=show_event)
    print(f"OpenQSP TCP Client\n\nServer: {args.host}:{args.port}")
    print("Authentication: callsign + password.")
    try:
        callsign = (args.callsign or input("Callsign: ")).strip().upper()
        password = (
            args.password
            if args.password is not None
            else getpass.getpass("Password: ")
        )
        client.connect()
        client.authenticate(callsign, password)
        print(f"\nConnected.\nIdentified as {callsign}.")
        session = CommandSession(client)
        running = True
        while running:
            try:
                line = input("\nopenqsp> ")
            except EOFError:
                break
            try:
                running, output = session.execute(line)
                if output:
                    print(output)
            except ClientError as error:
                print(f"Error: {error}")
                if not client.connected:
                    break
    except (ClientError, OSError) as error:
        print(f"Error: {error}")
        if args.debug:
            raise
        return 1
    except KeyboardInterrupt:
        print()
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
