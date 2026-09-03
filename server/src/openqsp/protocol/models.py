"""Immutable in-memory models for OpenQSP version 0.1 operations."""

from dataclasses import dataclass

from .constants import ErrorCode, Operation


@dataclass(frozen=True)
class SendMessage:
    created_at: int
    recipient: str
    body: str


@dataclass(frozen=True)
class GetNewMessages:
    since: int
    max: int


@dataclass(frozen=True)
class GetNewBulletins:
    since: int
    max: int


@dataclass(frozen=True)
class GetBulletin:
    sequence: int


@dataclass(frozen=True)
class GetCapabilities:
    pass


@dataclass(frozen=True)
class GetMessage:
    peer: str
    conversation_sequence: int


@dataclass(frozen=True)
class Capabilities:
    protocol_version: int
    capabilities: int


@dataclass(frozen=True)
class Message:
    sequence: int
    conversation_sequence: int
    created_at: int
    author: str
    recipient: str
    body: str


@dataclass(frozen=True)
class BulletinHeader:
    sequence: int
    created_at: int
    author: str
    title: str


@dataclass(frozen=True)
class Bulletin:
    sequence: int
    created_at: int
    author: str
    title: str
    body: str


@dataclass(frozen=True)
class End:
    request_operation: Operation
    returned_count: int
    next_since: int
    has_more: bool


@dataclass(frozen=True)
class Stored:
    pass


@dataclass(frozen=True)
class Error:
    # Zero is permitted when the request operation cannot be determined.
    request_operation: Operation | int
    error_code: ErrorCode
    detail: str
