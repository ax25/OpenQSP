"""Atomic persistence and idempotency handling for public bulletins."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing

from ._common import (
    MAX_SQLITE_INTEGER,
    MAX_U64,
    SequenceExhaustedError,
    StorageIntegrityError,
    StoreOutcome,
    StoreResult,
    length_prefixed,
    require_u64,
)
from .database import Database
from .migrations import decode_u64, encode_u64


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
