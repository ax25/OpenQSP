"""Efficient point lookup by incoming conversation sequence."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import closing

from ._common import MAX_U32, StorageIntegrityError, require_u32
from .messages import MessageStore, StoredMessage, _stored_message


def get_conversation_message(
    store: MessageStore,
    *,
    recipient: str,
    author: str,
    conversation_sequence: int,
) -> StoredMessage | None:
    """Return the Nth incoming message for ``(recipient, author)``.

    ``conversation_sequence`` is one-based and independent of the recipient-wide
    mailbox cursor.  This lookup is read-only and therefore cannot advance or
    otherwise mutate synchronization state.
    """
    require_u32("conversation_sequence", conversation_sequence)
    if conversation_sequence == 0:
        raise ValueError("conversation_sequence must be non-zero")
    if not isinstance(recipient, str) or not isinstance(author, str):
        raise TypeError("recipient and author must be strings")

    database = store._database  # Same package: use the store's configured DB.
    with closing(database.connect()) as connection:
        row = connection.execute(
            """SELECT mailbox_sequence,api_sequence,created_at,accepted_at,author,
                      recipient,body
                 FROM messages
                WHERE recipient=? AND author=?
                ORDER BY mailbox_sequence
                LIMIT 1 OFFSET ?""",
            (recipient, author, conversation_sequence - 1),
        ).fetchone()
    if row is None:
        return None
    value = _stored_message(row)
    if not 1 <= conversation_sequence <= MAX_U32:
        raise StorageIntegrityError("message conversation sequence is invalid")
    return value
