"""Bounded authentication wire constants shared by TCP client and server."""

MAX_HANDSHAKE_SIZE = 256
AUTH_PREFIX = b"AUTH "
HANDSHAKE_PREFIX = b"CALLSIGN "
HANDSHAKE_OK = b"OK\n"
HANDSHAKE_ERROR = b"ERROR\n"
