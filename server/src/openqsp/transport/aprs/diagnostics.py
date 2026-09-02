"""Human-readable APRS/OpenQSP diagnostics for server logs.

This module intentionally keeps its own bounded reassembly state. It is for
observability only and never participates in ACK, retry, replay, or Core request
processing.
"""

from __future__ import annotations

import re
import time

from openqsp.protocol import (
    Bulletin,
    BulletinHeader,
    Capabilities,
    End,
    Error,
    GetBulletin,
    GetCapabilities,
    GetNewBulletins,
    GetNewMessages,
    Message,
    SendMessage,
    Stored,
    decode_frame_with_flags,
)
from openqsp.protocol.constants import UNSOLICITED_FLAG

from .carriage import CarriageError, base36, base91_decode, parse_fragment
from .state import Reassembler, TransactionConflict

_ACK_RE = re.compile(r"ack([0-9A-Z]{1,5})")
_Q1_ACK_RE = re.compile(r"Q1A:([0-9A-Z]{3})")
_Q1_NACK_RE = re.compile(r"Q1N:([0-9A-Z]{3}):([0-9A-F]{4})")


class APRSFrameDiagnostics:
    """Decode APRS/OpenQSP controls and reassemble fragments for readable logs."""

    def __init__(self, *, ttl: float = 120.0, max_entries: int = 128) -> None:
        self._rx = Reassembler(ttl=ttl, max_entries=max_entries)
        self._tx = Reassembler(ttl=ttl, max_entries=max_entries)

    def describe_received(self, peer: str, body: str) -> str | None:
        return self._describe("rx", peer, body)

    def describe_sent(self, peer: str, body: str) -> str | None:
        return self._describe("tx", peer, body)

    def _describe(self, direction: str, peer: str, body: str) -> str | None:
        ack = _ACK_RE.fullmatch(body)
        if ack is not None:
            return f"APRS ACK message_id={ack.group(1)}"

        control = _describe_openqsp_control(body)
        if control is not None:
            return control

        try:
            fragment = parse_fragment(body)
        except (CarriageError, TypeError):
            return None

        profile = f"Q{fragment.version}"
        reassembler = self._rx if direction == "rx" else self._tx
        try:
            frame = reassembler.add(peer, fragment, time.monotonic())
        except (CarriageError, TransactionConflict) as exc:
            return (
                f"{profile} transaction={fragment.transaction_id} "
                f"fragment={fragment.index + 1}/{fragment.total} decode_error={exc}"
            )

        prefix = (
            f"{profile} transaction={fragment.transaction_id} "
            f"fragment={fragment.index + 1}/{fragment.total}"
        )
        if fragment.message_id is not None:
            prefix += f" message_id={fragment.message_id}"
        if frame is None:
            return f"{prefix} waiting_for_complete_frame"

        try:
            obj, flags = decode_frame_with_flags(frame)
        except Exception as exc:  # noqa: BLE001 - diagnostics must never affect transport
            return f"{prefix} core_decode_error={exc}"
        return f"{prefix} -> {format_core_object(obj, flags=flags)}"


def _describe_openqsp_control(body: str) -> str | None:
    if body.startswith("A2"):
        transaction = _decode_v2_control_transaction(body, expected_bytes=1)
        if transaction is not None:
            return f"A2 transaction={transaction} ACK"
        return None

    if body.startswith("S2"):
        transaction = _decode_v2_control_transaction(body, expected_bytes=1)
        if transaction is not None:
            return f"S2 transaction={transaction} STORED"
        return None

    if body.startswith("N2"):
        try:
            payload = base91_decode(body[2:])
        except CarriageError:
            return None
        if len(payload) != 3:
            return None
        transaction = base36(payload[0], 3)
        mask = int.from_bytes(payload[1:], "big")
        if mask == 0:
            return None
        missing = [str(index + 1) for index in range(16) if mask & (1 << index)]
        return (
            f"N2 transaction={transaction} missing={','.join(missing)} "
            f"mask=0x{mask:04X}"
        )

    legacy_ack = _Q1_ACK_RE.fullmatch(body)
    if legacy_ack is not None:
        return f"Q1A transaction={legacy_ack.group(1)} ACK"

    legacy_nack = _Q1_NACK_RE.fullmatch(body)
    if legacy_nack is not None:
        mask = int(legacy_nack.group(2), 16)
        if mask == 0:
            return None
        missing = [str(index + 1) for index in range(16) if mask & (1 << index)]
        return (
            f"Q1N transaction={legacy_nack.group(1)} missing={','.join(missing)} "
            f"mask=0x{mask:04X}"
        )
    return None


def _decode_v2_control_transaction(body: str, *, expected_bytes: int) -> str | None:
    try:
        payload = base91_decode(body[2:])
    except CarriageError:
        return None
    if len(payload) != expected_bytes:
        return None
    return base36(payload[0], 3)


def _operation_name(value: object) -> str:
    name = getattr(value, "name", None)
    return str(name) if name is not None else str(value)


def format_core_object(obj: object, *, flags: int = 0) -> str:
    """Return a compact one-line representation of one decoded Core object."""

    unsolicited = " unsolicited=true" if flags & UNSOLICITED_FLAG else ""

    match obj:
        case SendMessage(created_at=created_at, recipient=recipient, body=body):
            return (
                f"SEND_MESSAGE recipient={recipient} created_at={created_at} "
                f"body={body!r}"
            )
        case GetNewMessages(since=since, max=maximum):
            return f"GET_NEW_MESSAGES since={since} max={maximum}"
        case GetNewBulletins(since=since, max=maximum):
            return f"GET_NEW_BULLETINS since={since} max={maximum}"
        case GetBulletin(sequence=sequence):
            return f"GET_BULLETIN sequence={sequence}"
        case GetCapabilities():
            return "GET_CAPABILITIES"
        case Capabilities(protocol_version=version, capabilities=capabilities):
            return (
                f"CAPABILITIES protocol_version={version} "
                f"capabilities=0x{capabilities:08X}"
            )
        case Message(
            sequence=sequence,
            created_at=created_at,
            author=author,
            recipient=recipient,
            body=body,
        ):
            return (
                f"MESSAGE seq={sequence} from={author} to={recipient} "
                f"created_at={created_at} body={body!r}{unsolicited}"
            )
        case BulletinHeader(
            sequence=sequence,
            created_at=created_at,
            author=author,
            title=title,
        ):
            return (
                f"BULLETIN_HEADER seq={sequence} from={author} "
                f"created_at={created_at} title={title!r}{unsolicited}"
            )
        case Bulletin(
            sequence=sequence,
            created_at=created_at,
            author=author,
            title=title,
            body=body,
        ):
            return (
                f"BULLETIN seq={sequence} from={author} created_at={created_at} "
                f"title={title!r} body={body!r}"
            )
        case End(
            request_operation=request_operation,
            returned_count=returned_count,
            next_since=next_since,
            has_more=has_more,
        ):
            return (
                f"END request={_operation_name(request_operation)} "
                f"returned={returned_count} next_since={next_since} "
                f"has_more={str(has_more).lower()}"
            )
        case Stored():
            return "STORED"
        case Error(
            request_operation=request_operation,
            error_code=error_code,
            detail=detail,
        ):
            return (
                f"ERROR request={_operation_name(request_operation)} "
                f"code={_operation_name(error_code)} detail={detail!r}"
            )
        case _:
            return repr(obj)
