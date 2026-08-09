"""Persistent OpenQSP accounts and password verification."""

from __future__ import annotations

import base64
from contextlib import closing
import hashlib
import hmac
import os
import sqlite3
import time

from openqsp.protocol import normalize_callsign
from openqsp.protocol.errors import InvalidFieldError

from .database import Database

PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 16
DERIVED_KEY_BYTES = 32
MAX_PASSWORD_BYTES = 128
_DUMMY_SALT = b"OpenQSP-auth-v1!"


class AccountExistsError(ValueError):
    """A normalized callsign already has an account."""


class InvalidCredentialsError(ValueError):
    """Credentials are malformed or do not authenticate."""


def _password_bytes(password: object) -> bytes:
    if not isinstance(password, str):
        raise InvalidCredentialsError("invalid credentials")
    try:
        encoded = password.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidCredentialsError("invalid credentials") from None
    if not 1 <= len(encoded) <= MAX_PASSWORD_BYTES or b"\x00" in encoded:
        raise InvalidCredentialsError("invalid credentials")
    return encoded


def _derive(password: bytes, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password, salt, iterations, DERIVED_KEY_BYTES)


class AccountStore:
    """Administrative provisioning and constant-shape account authentication."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create_account(self, callsign: object, password: object) -> str:
        try:
            normalized = normalize_callsign(callsign)
        except InvalidFieldError:
            raise InvalidCredentialsError("invalid account data") from None
        secret = _password_bytes(password)
        salt = os.urandom(SALT_BYTES)
        derived = _derive(secret, salt)
        representation = "pbkdf2_sha256${}${}${}".format(
            PBKDF2_ITERATIONS,
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        )
        with closing(self.database.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO accounts(callsign, password_hash, created_at) VALUES (?, ?, ?)",
                    (normalized, representation, int(time.time())),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                connection.rollback()
                raise AccountExistsError("account already exists") from None
        return normalized

    def authenticate(self, callsign: object, password: object) -> str:
        """Return normalized identity or one non-enumerating failure."""
        secret = _password_bytes(password)
        try:
            normalized = normalize_callsign(callsign)
        except InvalidFieldError:
            normalized = "N0NONE"
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT password_hash FROM accounts WHERE callsign = ?", (normalized,)
            ).fetchone()
        valid = False
        if row is None:
            expected = _derive(secret, _DUMMY_SALT)
            hmac.compare_digest(expected, bytes(DERIVED_KEY_BYTES))
        else:
            try:
                algorithm, iterations_text, salt_text, expected_text = str(
                    row[0]
                ).split("$")
                if algorithm != "pbkdf2_sha256":
                    raise ValueError
                iterations = int(iterations_text)
                if not 100_000 <= iterations <= 10_000_000:
                    raise ValueError
                actual = _derive(
                    secret, base64.b64decode(salt_text, validate=True), iterations
                )
                expected = base64.b64decode(expected_text, validate=True)
                valid = hmac.compare_digest(actual, expected)
            except (ValueError, TypeError):
                valid = False
        if not valid or row is None:
            raise InvalidCredentialsError("invalid credentials")
        return normalized
