"""Atomic persistence for node-local public bulletins."""

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
    require_nonzero_u32,
    require_u32,
    validate_clock_value,
    validate_retrieval_limit,
    validate_stored_u32,
)
from .database import Database


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
    accepted_at: int
    author: str
    title: str
    body: str


@dataclass(frozen=True)
class BulletinPage:
    headers: tuple[StoredBulletinHeader, ...]
    next_since: int
    has_more: bool


class BulletinStore:
    def __init__(
        self, database: Database, *, clock: Callable[[], int] | None = None
    ) -> None:
        self._database = database
        self._clock = clock if clock is not None else lambda: int(time.time())

    def get_new_bulletins(self, *, since: int, limit: int) -> BulletinPage:
        require_u32("since", since)
        validate_retrieval_limit(limit)
        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN")
            try:
                state = connection.execute(
                    "SELECT last_value FROM bulletin_sequence WHERE singleton = 1"
                ).fetchone()
                if state is None:
                    raise StorageIntegrityError("bulletin sequence state is missing")
                highest = validate_stored_u32(
                    state["last_value"], "bulletin high-water", allow_zero=True
                )
                if since > highest:
                    raise InvalidCursorError(
                        f"bulletin cursor {since} is ahead of highest sequence {highest}"
                    )
                rows = connection.execute(
                    "SELECT sequence, created_at, author, title FROM bulletins WHERE sequence > ? ORDER BY sequence LIMIT ?",
                    (since, limit + 1),
                ).fetchall()
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        headers = tuple(_stored_header(row) for row in rows[:limit])
        return BulletinPage(
            headers, headers[-1].sequence if headers else since, len(rows) > limit
        )

    def get_bulletin(self, *, sequence: int) -> StoredBulletin | None:
        require_nonzero_u32("sequence", sequence)
        with closing(self._database.connect()) as connection:
            row = connection.execute(
                "SELECT sequence, created_at, accepted_at, author, title, body FROM bulletins WHERE sequence = ?",
                (sequence,),
            ).fetchone()
        return None if row is None else _stored_bulletin(row)

    def store_bulletin(
        self, *, created_at: int, author: str, title: str, body: str
    ) -> int:
        require_u32("created_at", created_at)
        if not isinstance(author, str) or not isinstance(title, str):
            raise TypeError("author and title must be strings")
        if not isinstance(body, str):
            raise TypeError("body must be a string")
        body_bytes = body.encode("utf-8")
        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                state = connection.execute(
                    "SELECT last_value FROM bulletin_sequence WHERE singleton = 1"
                ).fetchone()
                if state is None:
                    raise StorageIntegrityError("bulletin sequence state is missing")
                last = validate_stored_u32(
                    state["last_value"], "bulletin high-water", allow_zero=True
                )
                if last == MAX_U32:
                    raise SequenceExhaustedError("bulletin sequence is exhausted")
                sequence = last + 1
                accepted_at = validate_clock_value(self._clock())
                connection.execute(
                    "INSERT INTO bulletins(sequence, created_at, accepted_at, author, title, body) VALUES (?, ?, ?, ?, ?, ?)",
                    (sequence, created_at, accepted_at, author, title, body_bytes),
                )
                connection.execute(
                    "UPDATE bulletin_sequence SET last_value = ? WHERE singleton = 1",
                    (sequence,),
                )
                connection.commit()
                return sequence
            except BaseException:
                connection.rollback()
                raise


def _stored_header(row: sqlite3.Row) -> StoredBulletinHeader:
    sequence = validate_stored_u32(row["sequence"], "bulletin sequence")
    created_at = validate_stored_u32(
        row["created_at"], "bulletin created_at", allow_zero=True
    )
    author, title = row["author"], row["title"]
    if not isinstance(author, str) or not isinstance(title, str):
        raise StorageIntegrityError("bulletin author or title is not text")
    return StoredBulletinHeader(sequence, created_at, author, title)


def _stored_bulletin(row: sqlite3.Row) -> StoredBulletin:
    header = _stored_header(row)
    accepted_at, body = row["accepted_at"], row["body"]
    if (
        not isinstance(accepted_at, int)
        or isinstance(accepted_at, bool)
        or accepted_at < 0
    ):
        raise StorageIntegrityError("bulletin accepted_at is invalid")
    if not isinstance(body, bytes):
        raise StorageIntegrityError("bulletin body is not a BLOB")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StorageIntegrityError("bulletin body is not valid UTF-8") from error
    return StoredBulletin(
        header.sequence,
        header.created_at,
        accepted_at,
        header.author,
        header.title,
        text,
    )
