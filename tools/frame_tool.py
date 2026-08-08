#!/usr/bin/env python3
"""Inspect, validate, and generate OpenQSP Core v0.1 frames."""

from __future__ import annotations

import argparse
from dataclasses import fields
from enum import IntEnum
from pathlib import Path
import sys
from typing import Callable, TypeVar

# Make the production package importable from an uninstalled development checkout.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVER_SRC = REPOSITORY_ROOT / "server" / "src"
if str(SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(SERVER_SRC))

from openqsp.protocol.codec import decode_frame, encode_frame  # noqa: E402
from openqsp.protocol.constants import (  # noqa: E402
    HEADER_SIZE,
    AckStatus,
    ErrorCode,
    Operation,
)
from openqsp.protocol.errors import ProtocolError  # noqa: E402
from openqsp.protocol.models import (  # noqa: E402
    Ack,
    Bulletin,
    BulletinHeader,
    End,
    Error,
    GetBulletin,
    GetNewBulletins,
    GetNewMessages,
    Message,
    SendMessage,
)

EnumType = TypeVar("EnumType", bound=IntEnum)


def format_hex(data: bytes) -> str:
    """Return bytes in the canonical, space-separated hexadecimal format."""
    return data.hex(" ").upper()


def parse_hex(value: str) -> bytes:
    """Parse either compact or whitespace-separated hexadecimal input."""
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("invalid hexadecimal input") from exc


def parse_integer(value: str) -> int:
    """Parse a decimal or Python-style hexadecimal integer."""
    try:
        return int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid integer {value!r}; use decimal or 0x-prefixed hexadecimal"
        ) from exc


def enum_parser(enum_type: type[EnumType]) -> Callable[[str], EnumType]:
    """Build a case-insensitive argparse converter for an IntEnum."""
    def parse(value: str) -> EnumType:
        try:
            return enum_type[value.upper()]
        except KeyError as exc:
            choices = ", ".join(member.name for member in enum_type)
            raise argparse.ArgumentTypeError(
                f"unknown {enum_type.__name__} {value!r}; choose from: {choices}"
            ) from exc

    return parse


def parse_request_operation(value: str) -> Operation | int:
    if value == "0":
        return 0
    return enum_parser(Operation)(value)


def parse_boolean(value: str) -> bool:
    normalized = value.lower()
    if normalized in ("true", "1"):
        return True
    if normalized in ("false", "0"):
        return False
    raise argparse.ArgumentTypeError("boolean must be true, false, 1, or 0")


def _add_arguments(parser: argparse.ArgumentParser, *names: str) -> None:
    for name in names:
        parser.add_argument(f"--{name.replace('_', '-')}", required=True, type=parse_integer)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("decode", "validate"):
        subparser = commands.add_parser(command)
        subparser.add_argument("hex_frame", help="complete Core frame in hexadecimal")

    encode = commands.add_parser("encode")
    operations = encode.add_subparsers(dest="operation", required=True)

    send = operations.add_parser("SEND_MESSAGE")
    _add_arguments(send, "message_id", "created_at")
    send.add_argument("--recipient", required=True)
    send.add_argument("--body", required=True)

    for name in ("GET_NEW_MESSAGES", "GET_NEW_BULLETINS"):
        retrieval = operations.add_parser(name)
        _add_arguments(retrieval, "since", "max")

    get_bulletin = operations.add_parser("GET_BULLETIN")
    _add_arguments(get_bulletin, "bulletin_id")

    message = operations.add_parser("MESSAGE")
    _add_arguments(message, "sequence", "message_id", "created_at")
    for name in ("author", "recipient", "body"):
        message.add_argument(f"--{name}", required=True)

    header = operations.add_parser("BULLETIN_HEADER")
    _add_arguments(header, "sequence", "bulletin_id", "created_at")
    for name in ("author", "title"):
        header.add_argument(f"--{name}", required=True)

    bulletin = operations.add_parser("BULLETIN")
    _add_arguments(bulletin, "bulletin_id", "created_at")
    for name in ("author", "title", "body"):
        bulletin.add_argument(f"--{name}", required=True)

    end = operations.add_parser("END")
    end.add_argument("--request-operation", required=True, type=enum_parser(Operation))
    _add_arguments(end, "returned_count", "next_since")
    end.add_argument("--has-more", required=True, type=parse_boolean)

    ack = operations.add_parser("ACK")
    _add_arguments(ack, "object_id")
    ack.add_argument("--status", required=True, type=enum_parser(AckStatus))

    error = operations.add_parser("ERROR")
    error.add_argument("--request-operation", required=True, type=parse_request_operation)
    error.add_argument("--error-code", required=True, type=enum_parser(ErrorCode))
    error.add_argument("--detail", required=True)
    return parser


def build_model(args: argparse.Namespace) -> object:
    """Build the codec's typed model for an encode command."""
    values = vars(args)
    operation = values["operation"]
    model_types = {
        "SEND_MESSAGE": SendMessage,
        "GET_NEW_MESSAGES": GetNewMessages,
        "GET_NEW_BULLETINS": GetNewBulletins,
        "GET_BULLETIN": GetBulletin,
        "MESSAGE": Message,
        "BULLETIN_HEADER": BulletinHeader,
        "BULLETIN": Bulletin,
        "END": End,
        "ACK": Ack,
        "ERROR": Error,
    }
    model_type = model_types[operation]
    return model_type(**{field.name: values[field.name] for field in fields(model_type)})


def _display_value(value: object) -> str:
    if isinstance(value, IntEnum):
        return f"{value.name} (0x{value.value:02X})"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return f"{value} (0x{value:X})"
    return str(value)


def print_model(model: object, frame: bytes) -> None:
    """Print a stable human-readable view using the codec's decoded model."""
    canonical = encode_frame(model)  # Also obtains the operation without a parallel map.
    operation = Operation(canonical[1])
    print(f"Operation: {operation.name}")
    print(f"Frame size: {len(frame)} bytes")
    print(f"Payload size: {len(frame) - HEADER_SIZE} bytes")
    print()
    for field in fields(model):
        print(f"{field.name}: {_display_value(getattr(model, field.name))}")
    print("\nHex:")
    print(format_hex(canonical))


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) >= 2 and arguments[0].lower() == "encode":
        arguments[1] = arguments[1].upper()
    args = _build_parser().parse_args(arguments)
    if args.command == "encode":
        try:
            print(format_hex(encode_frame(build_model(args))))
            return 0
        except ProtocolError as exc:
            print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    try:
        frame = parse_hex(args.hex_frame)
    except ValueError:
        if args.command == "validate":
            print("INVALID")
            print("ValueError: invalid hexadecimal input")
        else:
            print("ERROR: invalid hexadecimal input", file=sys.stderr)
        return 1

    try:
        model = decode_frame(frame)
    except ProtocolError as exc:
        if args.command == "validate":
            print("INVALID")
            print(f"{type(exc).__name__}: {exc}")
        else:
            print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.command == "validate":
        canonical = encode_frame(model)
        print("VALID")
        print(f"Operation: {Operation(canonical[1]).name}")
    else:
        print_model(model, frame)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
