"""Atomic persistence and idempotency handling for public bulletins."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass

from ._common import (
    MAX_SQLITE_INTEGER,
    MAX_U64,
    InvalidCursorError,
    SequenceExhaustedError,
    StorageIntegrityError,
    StoreOutcome,
    StoreResult,
    length_prefixed,
    require_u64,
)
from .database import Database
from .migrations import decode_u64, encode_u64

MAX_RETRIEVAL_LIMIT = 20


@dataclass(frozen=True)
class StoredBulletinHeader:
    """Public metadata for one persisted bulletin."""

    sequence: int
    bulletin_id: int
    created_at: int
    author: str
    title: str


@dataclass(frozen=True)
class StoredBulletin:
    """One complete bulletin read from persistent storage."""

    bulletin_id: int
    created_at: int
    author: str
    title: str
    body: str


@dataclass(frozen=True)
class BulletinPage:
    """One incremental bulletin-header page and its cursor metadata."""

    headers: tuple[StoredBulletinHeader, ...]
    next_since: int
    has_more: bool


def bulletin_content_hash(
    *,
    bulletin_id: int,
    created_at: int,
    author: str,
    title: str,
    body: bytes,
) -> bytes:
    """Hash canonical bulletin content with a versioned, delimited encoding.

    The encoding is an internal storage detail rather than a protocol wire
    format. Every variable-length field has an eight-byte length prefix.
    """

    parts = (
        b"OpenQSP\x00bulletin-content\x00v1",
        encode_u64(bulletin_id),
        encode_u64(created_at),
        length_prefixed(author.encode("utf-8")),
        length_prefixed(title.encode("utf-8")),
        length_prefixed(body),
    )
    return hashlib.sha256(b"".join(parts)).digest()


class BulletinStore:
    """Persist validated public bulletins in short SQLite transactions."""

    def __init__(
        self, database: Database, *, clock: Callable[[], int] | None = None
    ) -> None:
        self._database = database
        self._clock = clock if clock is not None else lambda: int(time.time())

    def get_new_bulletins(self, *, since: int, limit: int) -> BulletinPage:
        """Return public bulletin headers after ``since`` in sequence order."""

        require_u64("since", since)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_RETRIEVAL_LIMIT
        ):
            raise ValueError(
                f"limit must be an integer between 1 and {MAX_RETRIEVAL_LIMIT}"
            )

        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN")
            try:
                sequence_row = connection.execute(
                    "SELECT last_value FROM sequences WHERE stream = 'bulletins'"
                ).fetchone()
                if sequence_row is None:
                    raise StorageIntegrityError("bulletins sequence state is missing")
                highest = _decode_stored_u64(
                    sequence_row["last_value"], field="bulletins last sequence"
                )
                if since > highest:
                    raise InvalidCursorError(
                        f"bulletin cursor {since} is ahead of highest sequence {highest}"
                    )
                rows = connection.execute(
                    """SELECT sequence, bulletin_id, created_at, author, title
                       FROM bulletins
                       WHERE sequence > ?
                       ORDER BY sequence ASC
                       LIMIT ?""",
                    (encode_u64(since), limit + 1),
                ).fetchall()
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

        has_more = len(rows) > limit
        headers = tuple(_stored_bulletin_header(row) for row in rows[:limit])
        next_since = headers[-1].sequence if headers else since
        return BulletinPage(headers, next_since, has_more)

    def get_bulletin(self, *, bulletin_id: int) -> StoredBulletin | None:
        """Return a complete bulletin by ID, or ``None`` when it is absent."""

        require_u64("bulletin_id", bulletin_id)
        with closing(self._database.connect()) as connection:
            row = connection.execute(
                """SELECT bulletin_id, created_at, author, title, body
                   FROM bulletins WHERE bulletin_id = ?""",
                (encode_u64(bulletin_id),),
            ).fetchone()
        return None if row is None else _stored_bulletin(row)

    def store_bulletin(
        self,
        *,
        bulletin_id: int,
        created_at: int,
        author: str,
        title: str,
        body: str,
    ) -> StoreOutcome:
        """Store a bulletin or classify an immutable-object retry.

        Protocol-level callsign and text constraints are assumed to have been
        checked. This boundary rejects only structurally unrepresentable data.
        """

        require_u64("bulletin_id", bulletin_id)
        require_u64("created_at", created_at)
        if created_at > MAX_SQLITE_INTEGER:
            raise ValueError("created_at cannot be represented by SQLite INTEGER")
        if not isinstance(author, str) or not isinstance(title, str):
            raise TypeError("author and title must be strings")
        if not isinstance(body, str):
            raise TypeError("body must be a string")

        body_bytes = body.encode("utf-8")
        object_id = encode_u64(bulletin_id)
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
                        title=title,
                        body=body_bytes,
                    )
                    connection.commit()
                    return outcome

                sequence_row = connection.execute(
                    "SELECT last_value FROM sequences WHERE stream = 'bulletins'"
                ).fetchone()
                if sequence_row is None:
                    raise StorageIntegrityError("bulletins sequence state is missing")
                last_sequence = decode_u64(sequence_row["last_value"])
                if last_sequence == MAX_U64:
                    raise SequenceExhaustedError("bulletin sequence is exhausted")
                sequence = last_sequence + 1

                accepted_at = self._clock()
                if (
                    not isinstance(accepted_at, int)
                    or isinstance(accepted_at, bool)
                    or not 0 <= accepted_at <= MAX_SQLITE_INTEGER
                ):
                    raise ValueError("clock must return a non-negative SQLite integer")

                content_hash = bulletin_content_hash(
                    bulletin_id=bulletin_id,
                    created_at=created_at,
                    author=author,
                    title=title,
                    body=body_bytes,
                )
                encoded_sequence = encode_u64(sequence)
                connection.execute(
                    "INSERT INTO objects(object_id, object_type) VALUES (?, 'bulletin')",
                    (object_id,),
                )
                connection.execute(
                    """INSERT INTO bulletins(
                           sequence, bulletin_id, created_at, accepted_at,
                           author, title, body, content_hash
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        encoded_sequence,
                        object_id,
                        created_at,
                        accepted_at,
                        author,
                        title,
                        body_bytes,
                        content_hash,
                    ),
                )
                connection.execute(
                    "UPDATE sequences SET last_value = ? WHERE stream = 'bulletins'",
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
        title: str,
        body: bytes,
    ) -> StoreOutcome:
        if object_type != "bulletin":
            return StoreOutcome(StoreResult.CONFLICT, None)

        row = connection.execute(
            """SELECT sequence, created_at, author, title, body
               FROM bulletins WHERE bulletin_id = ?""",
            (object_id,),
        ).fetchone()
        if row is None:
            raise StorageIntegrityError("bulletin object has no bulletin row")

        identical = (
            int(row["created_at"]) == created_at
            and str(row["author"]) == author
            and str(row["title"]) == title
            and bytes(row["body"]) == body
        )
        if identical:
            return StoreOutcome(
                StoreResult.ALREADY_STORED, decode_u64(row["sequence"])
            )
        return StoreOutcome(StoreResult.CONFLICT, None)


def _decode_stored_u64(value: object, *, field: str) -> int:
    if not isinstance(value, bytes):
        raise StorageIntegrityError(f"{field} is not an eight-byte BLOB")
    try:
        return decode_u64(value)
    except ValueError as error:
        raise StorageIntegrityError(f"{field} is not an eight-byte BLOB") from error


def _stored_bulletin_header(row: sqlite3.Row) -> StoredBulletinHeader:
    sequence = _decode_stored_u64(row["sequence"], field="bulletin sequence")
    bulletin_id = _decode_stored_u64(row["bulletin_id"], field="bulletin id")
    created_at = row["created_at"]
    author = row["author"]
    title = row["title"]
    if sequence == 0:
        raise StorageIntegrityError("bulletin sequence must be non-zero")
    if bulletin_id == 0:
        raise StorageIntegrityError("bulletin id must be non-zero")
    if (
        not isinstance(created_at, int)
        or isinstance(created_at, bool)
        or created_at < 0
    ):
        raise StorageIntegrityError("bulletin created_at is invalid")
    if not isinstance(author, str) or not isinstance(title, str):
        raise StorageIntegrityError("bulletin author or title is not text")
    return StoredBulletinHeader(sequence, bulletin_id, created_at, author, title)


def _stored_bulletin(row: sqlite3.Row) -> StoredBulletin:
    bulletin_id = _decode_stored_u64(row["bulletin_id"], field="bulletin id")
    created_at = row["created_at"]
    author = row["author"]
    title = row["title"]
    body = row["body"]
    if bulletin_id == 0:
        raise StorageIntegrityError("bulletin id must be non-zero")
    if (
        not isinstance(created_at, int)
        or isinstance(created_at, bool)
        or created_at < 0
    ):
        raise StorageIntegrityError("bulletin created_at is invalid")
    if not isinstance(author, str) or not isinstance(title, str):
        raise StorageIntegrityError("bulletin author or title is not text")
    if not isinstance(body, bytes):
        raise StorageIntegrityError("bulletin body is not a BLOB")
    try:
        decoded_body = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StorageIntegrityError("bulletin body is not valid UTF-8") from error
    return StoredBulletin(bulletin_id, created_at, author, title, decoded_body)
