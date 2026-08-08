"""Atomic persistence for mailbox-local private messages."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass

from ._common import (
    MAX_SQLITE_INTEGER,
    MAX_U32,
    InvalidCursorError,
    SequenceExhaustedError,
    StorageIntegrityError,
    require_u32,
)
from .database import Database

MAX_RETRIEVAL_LIMIT = 20


@dataclass(frozen=True)
class StoredMessage:
    sequence: int
    created_at: int
    accepted_at: int
    author: str
    recipient: str
    body: str


@dataclass(frozen=True)
class MessagePage:
    messages: tuple[StoredMessage, ...]
    next_since: int
    has_more: bool


class MessageStore:
    def __init__(
        self, database: Database, *, clock: Callable[[], int] | None = None
    ) -> None:
        self._database = database
        self._clock = clock if clock is not None else lambda: int(time.time())

    def get_new_messages(self, *, callsign: str, since: int, limit: int) -> MessagePage:
        """Return one page from a recipient's independent sequence space."""
        require_u32("since", since)
        _require_limit(limit)
        if not isinstance(callsign, str):
            raise TypeError("callsign must be a string")
        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN")
            try:
                state = connection.execute(
                    "SELECT last_value FROM mailbox_sequences WHERE recipient = ?",
                    (callsign,),
                ).fetchone()
                highest = (
                    0
                    if state is None
                    else _stored_u32(
                        state["last_value"], "mailbox high-water", allow_zero=True
                    )
                )
                if since > highest:
                    raise InvalidCursorError(
                        f"message cursor {since} is ahead of mailbox high-water {highest}"
                    )
                rows = connection.execute(
                    """SELECT mailbox_sequence, created_at, accepted_at, author, recipient, body
                       FROM messages WHERE recipient = ? AND mailbox_sequence > ?
                       ORDER BY mailbox_sequence LIMIT ?""",
                    (callsign, since, limit + 1),
                ).fetchall()
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        messages = tuple(_stored_message(row) for row in rows[:limit])
        return MessagePage(
            messages, messages[-1].sequence if messages else since, len(rows) > limit
        )

    def store_message(
        self, *, created_at: int, author: str, recipient: str, body: str
    ) -> int:
        require_u32("created_at", created_at)
        if not isinstance(author, str) or not isinstance(recipient, str):
            raise TypeError("author and recipient must be strings")
        if not isinstance(body, str):
            raise TypeError("body must be a string")
        body_bytes = body.encode("utf-8")
        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT last_value FROM mailbox_sequences WHERE recipient = ?",
                    (recipient,),
                ).fetchone()
                last = (
                    0
                    if row is None
                    else _stored_u32(
                        row["last_value"], "mailbox high-water", allow_zero=True
                    )
                )
                if last == MAX_U32:
                    raise SequenceExhaustedError("mailbox sequence is exhausted")
                sequence = last + 1
                accepted_at = _clock_value(self._clock())
                connection.execute(
                    """INSERT INTO mailbox_sequences(recipient, last_value) VALUES (?, ?)
                       ON CONFLICT(recipient) DO UPDATE SET last_value = excluded.last_value""",
                    (recipient, sequence),
                )
                connection.execute(
                    """INSERT INTO messages(recipient, mailbox_sequence, created_at, accepted_at, author, body)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (recipient, sequence, created_at, accepted_at, author, body_bytes),
                )
                connection.commit()
                return sequence
            except BaseException:
                connection.rollback()
                raise


def _require_limit(limit: int) -> None:
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_RETRIEVAL_LIMIT
    ):
        raise ValueError(
            f"limit must be an integer between 1 and {MAX_RETRIEVAL_LIMIT}"
        )


def _clock_value(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= MAX_SQLITE_INTEGER
    ):
        raise ValueError("clock must return a non-negative SQLite integer")
    return value


def _stored_u32(value: object, field: str, *, allow_zero: bool = False) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not (0 if allow_zero else 1) <= value <= MAX_U32
    ):
        raise StorageIntegrityError(f"{field} is not a valid unsigned 32-bit integer")
    return value


def _stored_message(row: sqlite3.Row) -> StoredMessage:
    sequence = _stored_u32(row["mailbox_sequence"], "message sequence")
    created_at = _stored_u32(row["created_at"], "message created_at", allow_zero=True)
    accepted_at = row["accepted_at"]
    author, recipient, body = row["author"], row["recipient"], row["body"]
    if (
        not isinstance(accepted_at, int)
        or isinstance(accepted_at, bool)
        or accepted_at < 0
    ):
        raise StorageIntegrityError("message accepted_at is invalid")
    if not isinstance(author, str) or not isinstance(recipient, str):
        raise StorageIntegrityError("message author or recipient is not text")
    if not isinstance(body, bytes):
        raise StorageIntegrityError("message body is not a BLOB")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StorageIntegrityError("message body is not valid UTF-8") from error
    return StoredMessage(sequence, created_at, accepted_at, author, recipient, text)
