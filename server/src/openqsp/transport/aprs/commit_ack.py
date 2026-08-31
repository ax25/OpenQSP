"""APRS SEND_MESSAGE commit-ACK negotiation helpers."""

COMMIT_ACK_PREFIX = "C"


def requested(message_id: str | None) -> bool:
    """Return whether a client opted into durable ACK semantics."""
    return message_id is not None and message_id.startswith(COMMIT_ACK_PREFIX)
