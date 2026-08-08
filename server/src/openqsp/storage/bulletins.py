"""Atomic persistence for node-local public bulletins."""

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
class StoredBulletinHeader:
    sequence: int
    created_at: int
    author: str
    title: str


@dataclass(frozen=True)
class StoredBulletin:
    sequence: int
    created_at: int
    author: str
    title: str
    body: str


@dataclass(frozen=True)
class BulletinPage:
    headers: tuple[StoredBulletinHeader, ...]
    next_since: int
    has_more: bool


class BulletinStore:
    """Persist bulletins using one node-local sequence as their identity."""

    def __init__(
        self, database: Database, *, clock: Callable[[], int] | None = None
    ) -> None:
        self._database = database
        self._clock = clock if clock is not None else lambda: int(time.time())

    def get_new_bulletins(self, *, since: int, limit: int) -> BulletinPage:
        require_u32("since", since)
        _require_limit(limit)
        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN")
            try:
                row = connection.execute(
                    "SELECT last_value FROM bulletin_sequence WHERE singleton = 1"
                ).fetchone()
                if row is None:
                    raise StorageIntegrityError("bulletin sequence state is missing")
                highest = _stored_u32(
                    row["last_value"], field="bulletin last sequence", allow_zero=True
                )
                if since > highest:
                    raise InvalidCursorError(
                        f"bulletin cursor {since} is ahead of highest sequence {highest}"
                    )
                rows = connection.execute(
                    """SELECT sequence, created_at, author, title
                       FROM bulletins WHERE sequence > ?
                       ORDER BY sequence ASC LIMIT ?""",
                    (since, limit + 1),
                ).fetchall()
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        has_more = len(rows) > limit
        headers = tuple(_stored_header(row) for row in rows[:limit])
        return BulletinPage(
            headers, headers[-1].sequence if headers else since, has_more
        )

    def get_bulletin(self, *, sequence: int) -> StoredBulletin | None:
        require_u32("sequence", sequence)
        if sequence == 0:
            raise ValueError("sequence must be non-zero")
        with closing(self._database.connect()) as connection:
            row = connection.execute(
                """SELECT sequence, created_at, author, title, body
                   FROM bulletins WHERE sequence = ?""",
                (sequence,),
            ).fetchone()
        return None if row is None else _stored_bulletin(row)

    def store_bulletin(
        self, *, created_at: int, author: str, title: str, body: str
    ) -> StoreOutcome:
        require_u32("created_at", created_at)
        if not isinstance(author, str) or not isinstance(title, str):
            raise TypeError("author and title must be strings")
        if not isinstance(body, str):
            raise TypeError("body must be a string")
        body_bytes = body.encode("utf-8")
        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT last_value FROM bulletin_sequence WHERE singleton = 1"
                ).fetchone()
                if row is None:
                    raise StorageIntegrityError("bulletin sequence state is missing")
                last = _stored_u32(
                    row["last_value"], field="bulletin last sequence", allow_zero=True
                )
                if last == MAX_U32:
                    raise SequenceExhaustedError("bulletin sequence is exhausted")
                sequence = last + 1
                accepted_at = self._clock()
                if (
                    not isinstance(accepted_at, int)
                    or isinstance(accepted_at, bool)
                    or not 0 <= accepted_at <= MAX_SQLITE_INTEGER
                ):
                    raise ValueError("clock must return a non-negative SQLite integer")
                connection.execute(
                    """INSERT INTO bulletins(
                           sequence, created_at, accepted_at, author, title, body
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (sequence, created_at, accepted_at, author, title, body_bytes),
                )
                connection.execute(
                    "UPDATE bulletin_sequence SET last_value = ? WHERE singleton = 1",
                    (sequence,),
                )
                connection.commit()
                return StoreOutcome(StoreResult.STORED, sequence)
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


def _stored_u32(value: object, *, field: str, allow_zero: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise StorageIntegrityError(f"{field} is not an integer")
    minimum = 0 if allow_zero else 1
    if not minimum <= value <= MAX_U32:
        raise StorageIntegrityError(f"{field} is outside its unsigned 32-bit range")
    return value


def _common(row: sqlite3.Row) -> tuple[int, int, str, str]:
    sequence = _stored_u32(row["sequence"], field="bulletin sequence")
    created_at, author, title = row["created_at"], row["author"], row["title"]
    if (
        not isinstance(created_at, int)
        or isinstance(created_at, bool)
        or created_at < 0
    ):
        raise StorageIntegrityError("bulletin created_at is invalid")
    if not isinstance(author, str) or not isinstance(title, str):
        raise StorageIntegrityError("bulletin author or title is not text")
    return sequence, created_at, author, title


def _stored_header(row: sqlite3.Row) -> StoredBulletinHeader:
    return StoredBulletinHeader(*_common(row))


def _stored_bulletin(row: sqlite3.Row) -> StoredBulletin:
    common = _common(row)
    body = row["body"]
    if not isinstance(body, bytes):
        raise StorageIntegrityError("bulletin body is not a BLOB")
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StorageIntegrityError("bulletin body is not valid UTF-8") from error
    return StoredBulletin(*common, decoded)
