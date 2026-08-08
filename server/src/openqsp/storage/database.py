"""SQLite connection and schema initialization support."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .migrations import LATEST_SCHEMA_VERSION, migrate


class UnsupportedSchemaVersionError(RuntimeError):
    """Raised when a database was created by newer OpenQSP software."""


class Database:
    """Own the configuration of connections to one SQLite database.

    Connections use explicit transactions (``isolation_level=None`` disables
    sqlite3's implicit transaction management). Callers that write data must
    therefore issue BEGIN and COMMIT/ROLLBACK deliberately. There is no
    connection pool: each call returns an independent caller-owned connection.
    """

    def __init__(self, path: str | Path, *, timeout: float = 10.0) -> None:
        self.path = str(path)
        self.timeout = timeout

    def connect(self) -> sqlite3.Connection:
        """Open and configure a connection; the caller must close it."""
        connection = sqlite3.connect(
            self.path,
            timeout=self.timeout,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        # WAL permits readers during a writer transaction. FULL ensures that a
        # successful commit is not intentionally acknowledged before syncing.
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def initialize(self) -> None:
        """Apply all pending migrations and verify the resulting version."""
        with closing(self.connect()) as connection:
            version = _schema_version(connection)
            if version > LATEST_SCHEMA_VERSION:
                raise UnsupportedSchemaVersionError(
                    f"database schema version {version} is newer than supported "
                    f"version {LATEST_SCHEMA_VERSION}"
                )
            migrate(connection, version)
            resulting_version = _schema_version(connection)
            if resulting_version != LATEST_SCHEMA_VERSION:
                raise RuntimeError(
                    "schema initialization finished at version "
                    f"{resulting_version}, expected {LATEST_SCHEMA_VERSION}"
                )

    def get_schema_version(self) -> int:
        """Return the database's current ``PRAGMA user_version`` value."""
        with closing(self.connect()) as connection:
            return _schema_version(connection)


def _schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    if row is None:  # pragma always returns one row, but keep failure explicit.
        raise RuntimeError("SQLite did not return a schema version")
    return int(row[0])
