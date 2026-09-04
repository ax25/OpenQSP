"""Persistent Q2 APRS transaction sequence allocation."""

from __future__ import annotations

from contextlib import closing

from .database import Database


class APRSTransactionSequenceStore:
    """Reserve Q2 transaction IDs durably per APRS endpoint.

    ``next_value`` is persisted before the reserved value is returned so an
    abrupt process restart cannot reuse a transaction ID that may already have
    reached RF/APRS-IS. Q2 uses one byte, so the sequence wraps at 256.
    """

    def __init__(self, database: Database) -> None:
        self._database = database
        self._initialize()

    def _initialize(self) -> None:
        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS aprs_transaction_sequences (
                           peer TEXT PRIMARY KEY,
                           next_value INTEGER NOT NULL
                               CHECK(typeof(next_value) = 'integer'
                                     AND next_value BETWEEN 0 AND 255)
                       ) WITHOUT ROWID"""
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def reserve(self, peer: str) -> int:
        """Atomically reserve and return the next Q2 transaction byte."""
        if not isinstance(peer, str) or not peer:
            raise ValueError("peer must be a non-empty string")
        with closing(self._database.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT next_value FROM aprs_transaction_sequences WHERE peer=?",
                    (peer,),
                ).fetchone()
                value = 0 if row is None else int(row["next_value"])
                next_value = (value + 1) & 0xFF
                connection.execute(
                    """INSERT INTO aprs_transaction_sequences(peer, next_value)
                       VALUES (?, ?)
                       ON CONFLICT(peer) DO UPDATE SET next_value=excluded.next_value""",
                    (peer, next_value),
                )
                connection.commit()
                return value
            except BaseException:
                connection.rollback()
                raise

    def next_value(self, peer: str) -> int:
        """Return the persisted next value without reserving it."""
        with closing(self._database.connect()) as connection:
            row = connection.execute(
                "SELECT next_value FROM aprs_transaction_sequences WHERE peer=?",
                (peer,),
            ).fetchone()
        return 0 if row is None else int(row["next_value"])
