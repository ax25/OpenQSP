"""Atomic persistence for mailbox-local private messages."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass

from ._common import (
    MAX_U32,
    InvalidCursorError,
    SequenceExhaustedError,
    StorageIntegrityError,
    require_u32,
    validate_clock_value,
    validate_retrieval_limit,
    validate_stored_u32,
)
from .database import Database


@dataclass(frozen=True)
class StoredMessage:
    sequence: int
    created_at: int
    accepted_at: int
    author: str
    recipient: str
    body: str
    api_sequence: int = 0


@dataclass(frozen=True)
class MessagePage:
    messages: tuple[StoredMessage, ...]
    next_since: int
    has_more: bool


@dataclass(frozen=True)
class Conversation:
    peer: str
    last_message: StoredMessage
    unread_count: int
    last_read_sequence: int


class MessageStore:
    def __init__(
        self, database: Database, *, clock: Callable[[], int] | None = None
    ) -> None:
        self._database = database
        self._clock = clock if clock is not None else lambda: int(time.time())

    def get_new_messages(self, *, callsign: str, since: int, limit: int) -> MessagePage:
        """Return one page from a recipient's independent sequence space."""
        require_u32("since", since)
        validate_retrieval_limit(limit)
        if not isinstance(callsign, str):
            raise TypeError("callsign must be a string")
        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN")
            try:
                state = connection.execute(
                    "SELECT last_value FROM mailbox_sequences WHERE recipient = ?",
                    (callsign,),
                ).fetchone()
                maximum_row = connection.execute(
                    "SELECT MAX(mailbox_sequence) FROM messages WHERE recipient = ?",
                    (callsign,),
                ).fetchone()
                maximum = maximum_row[0]
                if state is None:
                    if maximum is not None:
                        raise StorageIntegrityError(
                            "mailbox has messages but no sequence state"
                        )
                    highest = 0
                else:
                    highest = validate_stored_u32(
                        state["last_value"], "mailbox high-water", allow_zero=True
                    )
                    if maximum is not None:
                        maximum = validate_stored_u32(
                            maximum, "highest persisted message sequence"
                        )
                        if highest < maximum:
                            raise StorageIntegrityError(
                                "mailbox high-water is behind persisted messages"
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
                    else validate_stored_u32(
                        row["last_value"], "mailbox high-water", allow_zero=True
                    )
                )
                if last == MAX_U32:
                    raise SequenceExhaustedError("mailbox sequence is exhausted")
                sequence = last + 1
                accepted_at = validate_clock_value(self._clock())
                api_row = connection.execute(
                    "SELECT last_value FROM api_message_sequence WHERE singleton = 1"
                ).fetchone()
                api_sequence = int(api_row[0]) + 1
                connection.execute(
                    "UPDATE api_message_sequence SET last_value = ? WHERE singleton = 1",
                    (api_sequence,),
                )
                connection.execute(
                    """INSERT INTO mailbox_sequences(recipient, last_value) VALUES (?, ?)
                       ON CONFLICT(recipient) DO UPDATE SET last_value = excluded.last_value""",
                    (recipient, sequence),
                )
                connection.execute(
                    """INSERT INTO messages(recipient, mailbox_sequence, api_sequence,
                       created_at, accepted_at, author, body) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        recipient,
                        sequence,
                        api_sequence,
                        created_at,
                        accepted_at,
                        author,
                        body_bytes,
                    ),
                )
                connection.commit()
                return sequence
            except BaseException:
                connection.rollback()
                raise

    def store_message_idempotent(
        self,
        *,
        created_at: int,
        author: str,
        recipient: str,
        body: str,
        idempotency_key: str | None,
        request_hash: str,
    ) -> tuple[StoredMessage, bool]:
        """Atomically store a message, or return its keyed original result.

        Idempotency keys are transport metadata; the persisted message remains
        an ordinary OpenQSP domain message and uses the same sequences as every
        other ingress path.
        """
        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if idempotency_key is not None:
                    old = connection.execute(
                        """SELECT request_hash, recipient, mailbox_sequence FROM api_idempotency
                           WHERE author=? AND operation='send' AND idempotency_key=?""",
                        (author, idempotency_key),
                    ).fetchone()
                    if old is not None:
                        if old["request_hash"] != request_hash:
                            raise IdempotencyConflictError(
                                "key reused with another request"
                            )
                        row = connection.execute(
                            """SELECT mailbox_sequence, api_sequence, created_at, accepted_at,
                                      author, recipient, body FROM messages
                               WHERE recipient=? AND mailbox_sequence=?""",
                            (old["recipient"], old["mailbox_sequence"]),
                        ).fetchone()
                        connection.commit()
                        return _stored_message(row), False
                mailbox = connection.execute(
                    "SELECT last_value FROM mailbox_sequences WHERE recipient=?",
                    (recipient,),
                ).fetchone()
                sequence = (int(mailbox[0]) if mailbox else 0) + 1
                if sequence > MAX_U32:
                    raise SequenceExhaustedError("mailbox sequence is exhausted")
                api_sequence = (
                    int(
                        connection.execute(
                            "SELECT last_value FROM api_message_sequence WHERE singleton=1"
                        ).fetchone()[0]
                    )
                    + 1
                )
                accepted_at = validate_clock_value(self._clock())
                connection.execute(
                    """INSERT INTO mailbox_sequences(recipient,last_value) VALUES(?,?)
                       ON CONFLICT(recipient) DO UPDATE SET last_value=excluded.last_value""",
                    (recipient, sequence),
                )
                connection.execute(
                    "UPDATE api_message_sequence SET last_value=? WHERE singleton=1",
                    (api_sequence,),
                )
                connection.execute(
                    """INSERT INTO messages(recipient,mailbox_sequence,api_sequence,created_at,
                       accepted_at,author,body) VALUES(?,?,?,?,?,?,?)""",
                    (
                        recipient,
                        sequence,
                        api_sequence,
                        created_at,
                        accepted_at,
                        author,
                        body.encode(),
                    ),
                )
                if idempotency_key is not None:
                    connection.execute(
                        "INSERT INTO api_idempotency VALUES(?, 'send', ?, ?, ?, ?)",
                        (author, idempotency_key, request_hash, recipient, sequence),
                    )
                row = connection.execute(
                    """SELECT mailbox_sequence,api_sequence,created_at,accepted_at,author,
                              recipient,body FROM messages WHERE api_sequence=?""",
                    (api_sequence,),
                ).fetchone()
                connection.commit()
                return _stored_message(row), True
            except BaseException:
                connection.rollback()
                raise

    def api_list(
        self, *, callsign: str, after: int = 0, limit: int = 50, peer: str | None = None
    ) -> tuple[tuple[StoredMessage, ...], bool]:
        where = "(author=? OR recipient=?) AND api_sequence>?"
        args: list[object] = [callsign, callsign, after]
        if peer is not None:
            where += " AND ((author=? AND recipient=?) OR (author=? AND recipient=?))"
            args.extend((callsign, peer, peer, callsign))
        args.append(limit + 1)
        with closing(self._database.connect()) as connection:
            rows = connection.execute(
                f"""SELECT mailbox_sequence,api_sequence,created_at,accepted_at,author,
                            recipient,body FROM messages WHERE {where}
                     ORDER BY api_sequence LIMIT ?""",
                args,
            ).fetchall()
        return tuple(_stored_message(r) for r in rows[:limit]), len(rows) > limit

    def get_message(self, *, recipient: str, sequence: int) -> StoredMessage | None:
        with closing(self._database.connect()) as connection:
            row = connection.execute(
                """SELECT mailbox_sequence,api_sequence,created_at,accepted_at,author,
                          recipient,body FROM messages WHERE recipient=? AND mailbox_sequence=?""",
                (recipient, sequence),
            ).fetchone()
        return None if row is None else _stored_message(row)

    def api_high_water(self) -> int:
        with closing(self._database.connect()) as connection:
            return int(
                connection.execute(
                    "SELECT last_value FROM api_message_sequence WHERE singleton=1"
                ).fetchone()[0]
            )

    def conversations(self, *, callsign: str) -> tuple[Conversation, ...]:
        """Return conversation summaries without changing private read state."""
        with closing(self._database.connect()) as connection:
            rows = connection.execute(
                """WITH visible AS (
                       SELECT *, CASE WHEN author=? THEN recipient ELSE author END AS peer
                         FROM messages WHERE author=? OR recipient=?
                   ), latest AS (
                       SELECT peer, MAX(api_sequence) AS latest_api FROM visible GROUP BY peer
                   )
                   SELECT v.*, COALESCE(r.last_read_sequence, 0) AS last_read_sequence,
                          (SELECT COUNT(*) FROM messages incoming
                            WHERE incoming.recipient=? AND incoming.author=v.peer
                              AND incoming.mailbox_sequence >
                                  COALESCE(r.last_read_sequence, 0)) AS unread_count
                     FROM latest l JOIN visible v
                       ON v.peer=l.peer AND v.api_sequence=l.latest_api
                     LEFT JOIN conversation_reads r
                       ON r.owner_callsign=? AND r.peer_callsign=v.peer
                    ORDER BY v.api_sequence DESC""",
                (callsign, callsign, callsign, callsign, callsign),
            ).fetchall()
        return tuple(
            Conversation(
                row["peer"],
                _stored_message(row),
                int(row["unread_count"]),
                int(row["last_read_sequence"]),
            )
            for row in rows
        )

    def mark_conversation_read(self, *, owner: str, peer: str) -> int:
        """Atomically cover every currently persisted incoming message from peer."""
        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT COALESCE(MAX(mailbox_sequence), 0) FROM messages
                    WHERE recipient=? AND author=?""",
                (owner, peer),
            ).fetchone()
            sequence = int(row[0])
            connection.execute(
                """INSERT INTO conversation_reads VALUES(?,?,?)
                   ON CONFLICT(owner_callsign,peer_callsign) DO UPDATE SET
                   last_read_sequence=MAX(last_read_sequence,excluded.last_read_sequence)""",
                (owner, peer, sequence),
            )
            persisted = int(
                connection.execute(
                    """SELECT last_read_sequence FROM conversation_reads
                    WHERE owner_callsign=? AND peer_callsign=?""",
                    (owner, peer),
                ).fetchone()[0]
            )
            connection.commit()
        return persisted

    def set_delivery(
        self,
        *,
        recipient: str,
        sequence: int,
        transport: str,
        status: str,
        delivered_at: int | None = None,
    ) -> bool:
        """Apply a transport transition and report whether state changed.

        Delivered is terminal. A failed delivery must first be explicitly
        retried (moved to pending) before an acknowledgement can deliver it.
        """
        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """INSERT INTO deliveries VALUES(?,?,?,?,?)
                   ON CONFLICT(recipient,mailbox_sequence,transport) DO UPDATE SET
                   status=excluded.status, delivered_at=excluded.delivered_at
                   WHERE deliveries.status != 'delivered'
                     AND NOT(deliveries.status='failed' AND excluded.status='delivered')""",
                (recipient, sequence, transport, status, delivered_at),
            )
            connection.commit()
        return cursor.rowcount > 0


class IdempotencyConflictError(ValueError):
    pass


def _stored_message(row: sqlite3.Row) -> StoredMessage:
    sequence = validate_stored_u32(row["mailbox_sequence"], "message sequence")
    created_at = validate_stored_u32(
        row["created_at"], "message created_at", allow_zero=True
    )
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
    try:
        api_sequence = int(row["api_sequence"])
    except IndexError:
        # Legacy mailbox queries intentionally omit this API-only projection;
        # sqlite3.Row membership tests values rather than column names.
        api_sequence = 0
    return StoredMessage(
        sequence, created_at, accepted_at, author, recipient, text, api_sequence
    )
