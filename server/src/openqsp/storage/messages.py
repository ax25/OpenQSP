"""Atomic persistence and idempotency handling for private messages."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from enum import Enum

from .database import Database
from .migrations import decode_u64, encode_u64

MAX_U64 = 0xFFFF_FFFF_FFFF_FFFF
MAX_SQLITE_INTEGER = 0x7FFF_FFFF_FFFF_FFFF
MAX_RETRIEVAL_LIMIT = 20


class StoreResult(Enum):
    """Business outcomes from attempting to persist an immutable object."""

    STORED = "stored"
    ALREADY_STORED = "already_stored"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class StoreOutcome:
    """Result of storage, including the stable sequence when applicable."""

    result: StoreResult
    sequence: int | None


@dataclass(frozen=True)
class StoredMessage:
    """A private message read from persistent storage."""

    sequence: int
    message_id: int
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


class InvalidCursorError(ValueError):
    """Raised when a cursor is ahead of the node's global message stream."""


class SequenceExhaustedError(RuntimeError):
    """Raised when no further values exist in a u64 sequence space."""


class StorageIntegrityError(RuntimeError):
    """Raised when persisted rows violate the storage schema's invariants."""


def message_content_hash(
    *, message_id: int, created_at: int, author: str, recipient: str, body: bytes
) -> bytes:
    """Hash canonical message content using an unambiguous internal encoding.

    This encoding is deliberately storage-local, not a protocol wire format.
    Each variable-length byte field has an eight-byte length prefix.
    """

    encoded_author = author.encode("utf-8")
    encoded_recipient = recipient.encode("utf-8")
    parts = (
        b"OpenQSP\x00message-content\x00v1",
        encode_u64(message_id),
        encode_u64(created_at),
        _length_prefixed(encoded_author),
        _length_prefixed(encoded_recipient),
        _length_prefixed(body),
    )
    return hashlib.sha256(b"".join(parts)).digest()


class MessageStore:
    """Persist validated private messages in short SQLite transactions."""

    def __init__(
        self, database: Database, *, clock: Callable[[], int] | None = None
    ) -> None:
        self._database = database
        self._clock = clock if clock is not None else lambda: int(time.time())

    def get_new_messages(
        self, *, callsign: str, since: int, limit: int
    ) -> MessagePage:
        """Return messages addressed to ``callsign`` after ``since``.

        Cursor validity is checked against the global message sequence rather
        than this recipient's visible rows. The read transaction keeps that
        check and the paginated query on one consistent SQLite snapshot.
        """

        _require_u64("since", since)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_RETRIEVAL_LIMIT
        ):
            raise ValueError(
                f"limit must be an integer between 1 and {MAX_RETRIEVAL_LIMIT}"
            )
        if not isinstance(callsign, str):
            raise TypeError("callsign must be a string")

        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN")
            try:
                sequence_row = connection.execute(
                    "SELECT last_value FROM sequences WHERE stream = 'messages'"
                ).fetchone()
                if sequence_row is None:
                    raise StorageIntegrityError("messages sequence state is missing")
                highest = _decode_stored_u64(
                    sequence_row["last_value"], field="messages last sequence"
                )
                if since > highest:
                    raise InvalidCursorError(
                        f"message cursor {since} is ahead of highest sequence {highest}"
                    )

                rows = connection.execute(
                    """SELECT sequence, message_id, created_at, author, recipient, body
                       FROM messages
                       WHERE recipient = ? AND sequence > ?
                       ORDER BY sequence ASC
                       LIMIT ?""",
                    (callsign, encode_u64(since), limit + 1),
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
        message_id: int,
        created_at: int,
        author: str,
        recipient: str,
        body: str,
    ) -> StoreOutcome:
        """Store a new message or classify an immutable-object retry.

        Protocol-level callsign and body limits are assumed to have already
        been checked. This boundary only rejects values that cannot be safely
        represented by the storage schema.
        """

        _require_u64("message_id", message_id)
        _require_u64("created_at", created_at)
        if created_at > MAX_SQLITE_INTEGER:
            raise ValueError("created_at cannot be represented by SQLite INTEGER")
        if not isinstance(author, str) or not isinstance(recipient, str):
            raise TypeError("author and recipient must be strings")
        if not isinstance(body, str):
            raise TypeError("body must be a string")
        body_bytes = body.encode("utf-8")
        object_id = encode_u64(message_id)

        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing_object = connection.execute(
                    "SELECT object_type FROM objects WHERE object_id = ?",
                    (object_id,),
                ).fetchone()
                if existing_object is not None:
                    outcome = self._classify_existing(
                        connection,
                        object_id=object_id,
                        object_type=str(existing_object["object_type"]),
                        created_at=created_at,
                        author=author,
                        recipient=recipient,
                        body=body_bytes,
                    )
                    connection.commit()
                    return outcome

                sequence_row = connection.execute(
                    "SELECT last_value FROM sequences WHERE stream = 'messages'"
                ).fetchone()
                if sequence_row is None:
                    raise StorageIntegrityError("messages sequence state is missing")
                last_sequence = decode_u64(sequence_row["last_value"])
                if last_sequence == MAX_U64:
                    raise SequenceExhaustedError("message sequence is exhausted")
                sequence = last_sequence + 1
                accepted_at = self._clock()
                if (
                    not isinstance(accepted_at, int)
                    or isinstance(accepted_at, bool)
                    or not 0 <= accepted_at <= MAX_SQLITE_INTEGER
                ):
                    raise ValueError("clock must return a non-negative SQLite integer")

                content_hash = message_content_hash(
                    message_id=message_id,
                    created_at=created_at,
                    author=author,
                    recipient=recipient,
                    body=body_bytes,
                )
                encoded_sequence = encode_u64(sequence)
                connection.execute(
                    "INSERT INTO objects(object_id, object_type) VALUES (?, 'message')",
                    (object_id,),
                )
                connection.execute(
                    """INSERT INTO messages(
                           sequence, message_id, created_at, accepted_at,
                           author, recipient, body, content_hash
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        encoded_sequence,
                        object_id,
                        created_at,
                        accepted_at,
                        author,
                        recipient,
                        body_bytes,
                        content_hash,
                    ),
                )
                connection.execute(
                    "UPDATE sequences SET last_value = ? WHERE stream = 'messages'",
                    (encoded_sequence,),
                )
                connection.commit()
                return StoreOutcome(StoreResult.STORED, sequence)
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _classify_existing(
        connection: sqlite3.Connection,
        *,
        object_id: bytes,
        object_type: str,
        created_at: int,
        author: str,
        recipient: str,
        body: bytes,
    ) -> StoreOutcome:
        if object_type != "message":
            return StoreOutcome(StoreResult.CONFLICT, None)

        row = connection.execute(
            """SELECT sequence, created_at, author, recipient, body
               FROM messages WHERE message_id = ?""",
            (object_id,),
        ).fetchone()
        if row is None:
            raise StorageIntegrityError("message object has no message row")

        identical = (
            int(row["created_at"]) == created_at
            and str(row["author"]) == author
            and str(row["recipient"]) == recipient
            and bytes(row["body"]) == body
        )
        if identical:
            return StoreOutcome(
                StoreResult.ALREADY_STORED, decode_u64(row["sequence"])
            )
        return StoreOutcome(StoreResult.CONFLICT, None)


def _length_prefixed(value: bytes) -> bytes:
    return len(value).to_bytes(8, "big") + value


def _require_u64(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_U64:
        raise ValueError(f"{name} must be an unsigned 64-bit integer")


def _decode_stored_u64(value: object, *, field: str) -> int:
    if not isinstance(value, bytes):
        raise StorageIntegrityError(f"{field} is not an eight-byte BLOB")
    try:
        return decode_u64(value)
    except ValueError as error:
        raise StorageIntegrityError(f"{field} is not an eight-byte BLOB") from error


def _stored_message(row: sqlite3.Row) -> StoredMessage:
    sequence = _decode_stored_u64(row["sequence"], field="message sequence")
    message_id = _decode_stored_u64(row["message_id"], field="message id")
    created_at = row["created_at"]
    author = row["author"]
    recipient = row["recipient"]
    body = row["body"]
    if sequence == 0:
        raise StorageIntegrityError("message sequence must be non-zero")
    if message_id == 0:
        raise StorageIntegrityError("message id must be non-zero")
    if not isinstance(created_at, int) or isinstance(created_at, bool) or created_at < 0:
        raise StorageIntegrityError("message created_at is invalid")
    if not isinstance(author, str) or not isinstance(recipient, str):
        raise StorageIntegrityError("message author or recipient is not text")
    if not isinstance(body, bytes):
        raise StorageIntegrityError("message body is not a BLOB")
    try:
        decoded_body = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StorageIntegrityError("message body is not valid UTF-8") from error
    return StoredMessage(
        sequence, message_id, created_at, author, recipient, decoded_body
    )
