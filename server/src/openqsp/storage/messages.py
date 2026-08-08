"""Atomic persistence for recipient-local private-message mailboxes."""

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
    StoreOutcome,
    StoreResult,
    require_u32,
)
from .database import Database

MAX_RETRIEVAL_LIMIT = 20


@dataclass(frozen=True)
class StoredMessage:
    """A private message read from one recipient's mailbox."""

    sequence: int
    created_at: int
    author: str
    recipient: str
    body: str


@dataclass(frozen=True)
class MessagePage:
    """One incremental mailbox page and its stateless cursor metadata."""

    messages: tuple[StoredMessage, ...]
    next_since: int
    has_more: bool


class MessageStore:
    """Persist messages with atomic, recipient-local sequence allocation."""

    def __init__(
        self, database: Database, *, clock: Callable[[], int] | None = None
    ) -> None:
        self._database = database
        self._clock = clock if clock is not None else lambda: int(time.time())

    def get_new_messages(self, *, callsign: str, since: int, limit: int) -> MessagePage:
        """Return messages in ``callsign``'s mailbox after ``since``."""
        require_u32("since", since)
        _require_limit(limit)
        if not isinstance(callsign, str):
            raise TypeError("callsign must be a string")

        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN")
            try:
                row = connection.execute(
                    "SELECT last_value FROM mailbox_sequences WHERE recipient = ?",
                    (callsign,),
                ).fetchone()
                highest = (
                    0
                    if row is None
                    else _stored_u32(
                        row["last_value"],
                        field="mailbox last sequence",
                        allow_zero=True,
                    )
                )
                if since > highest:
                    raise InvalidCursorError(
                        f"message cursor {since} is ahead of mailbox sequence {highest}"
                    )
                rows = connection.execute(
                    """SELECT mailbox_sequence, created_at, author, recipient, body
                       FROM messages
                       WHERE recipient = ? AND mailbox_sequence > ?
                       ORDER BY mailbox_sequence ASC
                       LIMIT ?""",
                    (callsign, since, limit + 1),
                ).fetchall()
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

        has_more = len(rows) > limit
        messages = tuple(_stored_message(row) for row in rows[:limit])
        next_since = messages[-1].sequence if messages else since
        return MessagePage(messages, next_since, has_more)

    def store_message(
        self,
        *,
        created_at: int,
        author: str,
        recipient: str,
        body: str,
    ) -> StoreOutcome:
        """Allocate and durably insert the next recipient-local sequence."""
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
                last_sequence = (
                    0
                    if row is None
                    else _stored_u32(
                        row["last_value"],
                        field="mailbox last sequence",
                        allow_zero=True,
                    )
                )
                if last_sequence == MAX_U32:
                    raise SequenceExhaustedError("mailbox sequence is exhausted")
                sequence = last_sequence + 1
                accepted_at = self._accepted_at()

                connection.execute(
                    """INSERT INTO messages(
                           recipient, mailbox_sequence, author, created_at,
                           accepted_at, body
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (recipient, sequence, author, created_at, accepted_at, body_bytes),
                )
                connection.execute(
                    """INSERT INTO mailbox_sequences(recipient, last_value)
                       VALUES (?, ?)
                       ON CONFLICT(recipient)
                       DO UPDATE SET last_value = excluded.last_value""",
                    (recipient, sequence),
                )
                connection.commit()
                return StoreOutcome(StoreResult.STORED, sequence)
            except BaseException:
                connection.rollback()
                raise

    def _accepted_at(self) -> int:
        value = self._clock()
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= MAX_SQLITE_INTEGER
        ):
            raise ValueError("clock must return a non-negative SQLite integer")
        return value


def _require_limit(limit: int) -> None:
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_RETRIEVAL_LIMIT
    ):
        raise ValueError(
            f"limit must be an integer between 1 and {MAX_RETRIEVAL_LIMIT}"
        )


def _stored_u32(value: object, *, field: str, allow_zero: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise StorageIntegrityError(f"{field} is not an integer")
    minimum = 0 if allow_zero else 1
    if not minimum <= value <= MAX_U32:
        raise StorageIntegrityError(f"{field} is outside its unsigned 32-bit range")
    return value


def _stored_message(row: sqlite3.Row) -> StoredMessage:
    sequence = _stored_u32(row["mailbox_sequence"], field="message sequence")
    created_at = row["created_at"]
    author, recipient, body = row["author"], row["recipient"], row["body"]
    if (
        not isinstance(created_at, int)
        or isinstance(created_at, bool)
        or created_at < 0
    ):
        raise StorageIntegrityError("message created_at is invalid")
    if not isinstance(author, str) or not isinstance(recipient, str):
        raise StorageIntegrityError("message author or recipient is not text")
    if not isinstance(body, bytes):
        raise StorageIntegrityError("message body is not a BLOB")
    try:
        decoded_body = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StorageIntegrityError("message body is not valid UTF-8") from error
    return StoredMessage(sequence, created_at, author, recipient, decoded_body)
