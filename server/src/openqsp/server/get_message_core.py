"""ServerCore extension for selective private-message repair."""

from __future__ import annotations

from openqsp.protocol import Error, ErrorCode, GetMessage, Message, Operation, ProtocolObject, validate_callsign
from openqsp.protocol.errors import InvalidFieldError
from openqsp.storage import StorageIntegrityError
from openqsp.storage.conversation_lookup import get_conversation_message

from .core import RequestContext, ServerCore as _BaseServerCore


class ServerCore(_BaseServerCore):
    """Core with GET_MESSAGE selective retrieval support."""

    def _dispatch(self, context: RequestContext, request: ProtocolObject) -> list[ProtocolObject]:
        if isinstance(request, GetMessage):
            return self._handle_get_message(context, request)
        return super()._dispatch(context, request)

    def _handle_get_message(self, context: RequestContext, request: GetMessage) -> list[ProtocolObject]:
        if self._message_store is None:
            return [Error(Operation.GET_MESSAGE, ErrorCode.BUSY, "message store unavailable")]
        try:
            recipient = validate_callsign(context.authenticated_callsign, "authenticated_callsign")
            peer = validate_callsign(request.peer, "peer")
        except InvalidFieldError:
            return [Error(Operation.GET_MESSAGE, ErrorCode.UNAUTHORIZED, "invalid callsign")]

        try:
            stored = get_conversation_message(
                self._message_store,
                recipient=recipient,
                author=peer,
                conversation_sequence=request.conversation_sequence,
            )
        except (StorageIntegrityError, ValueError):
            return [
                Error(
                    Operation.GET_MESSAGE,
                    ErrorCode.INTERNAL_ERROR,
                    "message storage integrity failure",
                )
            ]

        if stored is None:
            return [Error(Operation.GET_MESSAGE, ErrorCode.NOT_FOUND, "message not found")]

        return [
            Message(
                stored.sequence,
                request.conversation_sequence,
                stored.created_at,
                stored.author,
                stored.recipient,
                stored.body,
            )
        ]
