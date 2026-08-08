"""OpenQSP Core request decoding, dispatch, and response encoding.

Transport and authentication layers are responsible for supplying a verified
callsign and one complete Core frame.  This module deliberately has no concept
of connections or sessions.
"""

from __future__ import annotations

from dataclasses import dataclass

from openqsp.protocol import (
    Bulletin,
    BulletinHeader,
    End,
    Error,
    ErrorCode,
    GetBulletin,
    GetNewBulletins,
    GetNewMessages,
    Message,
    Operation,
    ProtocolObject,
    SendMessage,
    Stored,
    decode_frame,
    encode_frame,
    validate_callsign,
)
from openqsp.protocol.errors import (
    InvalidFieldError,
    PayloadLengthError,
    ProtocolDecodeError,
    UnknownOperationError,
    UnsupportedVersionError,
)
from openqsp.storage import (
    BulletinStore,
    InvalidCursorError,
    MessageStore,
    SequenceExhaustedError,
    StorageIntegrityError,
)


@dataclass(frozen=True)
class RequestContext:
    """Trusted information supplied outside the client-controlled frame."""

    authenticated_callsign: str


class ServerCore:
    """Decode and dispatch complete Core frames without transport concerns.

    Stores are injected once so handlers can use them without creating global
    state or opening a database as part of dispatch.
    """

    def __init__(
        self,
        *,
        message_store: MessageStore | None = None,
        bulletin_store: BulletinStore | None = None,
    ) -> None:
        self._message_store = message_store
        self._bulletin_store = bulletin_store

    def handle_frame(
        self, authenticated_callsign: str, frame_bytes: bytes
    ) -> list[bytes]:
        """Handle one request frame and return zero or more response frames.

        A frame shorter than the common header is silently discarded because
        it contains too little information to construct a meaningful protocol
        response.  Other codec failures are converted to one protocol ERROR.
        """

        if not isinstance(authenticated_callsign, str):
            raise TypeError("authenticated_callsign must be a string")

        try:
            request = decode_frame(frame_bytes)
        except (ProtocolDecodeError, InvalidFieldError) as error:
            response = self._decode_error_response(frame_bytes, error)
            return [] if response is None else [encode_frame(response)]

        context = RequestContext(authenticated_callsign)
        responses = self._dispatch(context, request)
        return [encode_frame(response) for response in responses]

    def _dispatch(
        self, context: RequestContext, request: ProtocolObject
    ) -> list[ProtocolObject]:
        # Keep each request operation visible here: later milestones can fill
        # in one handler without changing request classification.
        if isinstance(request, SendMessage):
            return self._handle_send_message(context, request)
        if isinstance(request, GetNewMessages):
            return self._handle_get_new_messages(context, request)
        if isinstance(request, GetNewBulletins):
            return self._handle_get_new_bulletins(context, request)
        if isinstance(request, GetBulletin):
            return self._handle_get_bulletin(context, request)

        return [
            Error(
                self._operation_for(request),
                ErrorCode.UNKNOWN_OPERATION,
                "operation is not a client request",
            )
        ]

    def _handle_send_message(
        self, context: RequestContext, request: SendMessage
    ) -> list[ProtocolObject]:
        if self._message_store is None:
            return [
                Error(
                    Operation.SEND_MESSAGE,
                    ErrorCode.BUSY,
                    "message store unavailable",
                )
            ]

        try:
            author = validate_callsign(
                context.authenticated_callsign, "authenticated_callsign"
            )
        except InvalidFieldError:
            return [
                Error(
                    Operation.SEND_MESSAGE,
                    ErrorCode.UNAUTHORIZED,
                    "invalid authenticated callsign",
                )
            ]

        try:
            self._message_store.store_message(
                created_at=request.created_at,
                author=author,
                recipient=request.recipient,
                body=request.body,
            )
        except SequenceExhaustedError:
            return [
                Error(
                    Operation.SEND_MESSAGE,
                    ErrorCode.BUSY,
                    "message storage exhausted",
                )
            ]
        except StorageIntegrityError:
            return [
                Error(
                    Operation.SEND_MESSAGE,
                    ErrorCode.INTERNAL_ERROR,
                    "message storage integrity failure",
                )
            ]

        return [Stored()]

    def _handle_get_new_messages(
        self, context: RequestContext, request: GetNewMessages
    ) -> list[ProtocolObject]:
        if self._message_store is None:
            return [
                Error(
                    Operation.GET_NEW_MESSAGES,
                    ErrorCode.BUSY,
                    "message store unavailable",
                )
            ]

        try:
            callsign = validate_callsign(
                context.authenticated_callsign, "authenticated_callsign"
            )
        except InvalidFieldError:
            return [
                Error(
                    Operation.GET_NEW_MESSAGES,
                    ErrorCode.UNAUTHORIZED,
                    "invalid authenticated callsign",
                )
            ]

        try:
            page = self._message_store.get_new_messages(
                callsign=callsign,
                since=request.since,
                limit=request.max,
            )
        except InvalidCursorError:
            return [
                Error(
                    Operation.GET_NEW_MESSAGES,
                    ErrorCode.INVALID_CURSOR,
                    "invalid message cursor",
                )
            ]
        except StorageIntegrityError:
            return [
                Error(
                    Operation.GET_NEW_MESSAGES,
                    ErrorCode.INTERNAL_ERROR,
                    "message storage integrity failure",
                )
            ]

        responses: list[ProtocolObject] = [
            Message(
                message.sequence,
                message.created_at,
                message.author,
                message.recipient,
                message.body,
            )
            for message in page.messages
        ]
        responses.append(
            End(
                Operation.GET_NEW_MESSAGES,
                len(page.messages),
                page.next_since,
                page.has_more,
            )
        )
        return responses

    def _handle_get_new_bulletins(
        self, context: RequestContext, request: GetNewBulletins
    ) -> list[ProtocolObject]:
        if self._bulletin_store is None:
            return [
                Error(
                    Operation.GET_NEW_BULLETINS,
                    ErrorCode.BUSY,
                    "bulletin store unavailable",
                )
            ]

        try:
            validate_callsign(
                context.authenticated_callsign, "authenticated_callsign"
            )
        except InvalidFieldError:
            return [
                Error(
                    Operation.GET_NEW_BULLETINS,
                    ErrorCode.UNAUTHORIZED,
                    "invalid authenticated callsign",
                )
            ]

        try:
            page = self._bulletin_store.get_new_bulletins(
                since=request.since,
                limit=request.max,
            )
        except InvalidCursorError:
            return [
                Error(
                    Operation.GET_NEW_BULLETINS,
                    ErrorCode.INVALID_CURSOR,
                    "invalid bulletin cursor",
                )
            ]
        except StorageIntegrityError:
            return [
                Error(
                    Operation.GET_NEW_BULLETINS,
                    ErrorCode.INTERNAL_ERROR,
                    "bulletin storage integrity failure",
                )
            ]

        responses: list[ProtocolObject] = [
            BulletinHeader(
                header.sequence,
                header.created_at,
                header.author,
                header.title,
            )
            for header in page.headers
        ]
        responses.append(
            End(
                Operation.GET_NEW_BULLETINS,
                len(page.headers),
                page.next_since,
                page.has_more,
            )
        )
        return responses

    def _handle_get_bulletin(
        self, context: RequestContext, request: GetBulletin
    ) -> list[ProtocolObject]:
        if self._bulletin_store is None:
            return [
                Error(
                    Operation.GET_BULLETIN,
                    ErrorCode.BUSY,
                    "bulletin store unavailable",
                )
            ]

        try:
            validate_callsign(
                context.authenticated_callsign, "authenticated_callsign"
            )
        except InvalidFieldError:
            return [
                Error(
                    Operation.GET_BULLETIN,
                    ErrorCode.UNAUTHORIZED,
                    "invalid authenticated callsign",
                )
            ]

        try:
            bulletin = self._bulletin_store.get_bulletin(sequence=request.sequence)
        except StorageIntegrityError:
            return [
                Error(
                    Operation.GET_BULLETIN,
                    ErrorCode.INTERNAL_ERROR,
                    "bulletin storage integrity failure",
                )
            ]

        if bulletin is None:
            return [
                Error(
                    Operation.GET_BULLETIN,
                    ErrorCode.NOT_FOUND,
                    "bulletin not found",
                )
            ]

        return [
            Bulletin(
                bulletin.sequence,
                bulletin.created_at,
                bulletin.author,
                bulletin.title,
                bulletin.body,
            )
        ]

    @staticmethod
    def _operation_for(value: ProtocolObject) -> Operation:
        if isinstance(value, Message):
            return Operation.MESSAGE
        if isinstance(value, BulletinHeader):
            return Operation.BULLETIN_HEADER
        if isinstance(value, Bulletin):
            return Operation.BULLETIN
        if isinstance(value, End):
            return Operation.END
        if isinstance(value, Stored):
            return Operation.STORED
        if isinstance(value, Error):
            return Operation.ERROR
        raise TypeError(f"unclassified protocol object: {type(value).__name__}")

    @staticmethod
    def _decode_error_response(
        frame: object, error: ProtocolDecodeError | InvalidFieldError
    ) -> Error | None:
        if not isinstance(frame, bytes) or len(frame) < 4:
            return None

        operation: Operation | int = 0
        if frame[0] == 1:
            try:
                operation = Operation(frame[1])
            except ValueError:
                pass

        if isinstance(error, UnsupportedVersionError):
            code = ErrorCode.UNSUPPORTED_VERSION
            operation = 0
        elif isinstance(error, UnknownOperationError):
            code = ErrorCode.UNKNOWN_OPERATION
            operation = 0
        elif isinstance(error, InvalidFieldError) and frame[2] != 0:
            code = ErrorCode.INVALID_FRAME
        elif isinstance(error, InvalidFieldError):
            code = ErrorCode.INVALID_FIELD
        elif isinstance(error, PayloadLengthError):
            code = ErrorCode.INVALID_FRAME
        else:
            code = ErrorCode.INVALID_FRAME

        return Error(operation, code, str(error)[:64])
