"""Focused M5.1 application-session tests with no transport dependencies."""

import asyncio

import pytest

from openqsp.protocol import (
    Error,
    ErrorCode,
    GetNewMessages,
    Operation,
    decode_frame,
    encode_frame,
)
from openqsp.server import (
    ApplicationSession,
    SessionClosedError,
    SessionRegistry,
    SessionState,
)


class RecordingHandler:
    def __init__(self, *, fail: bool = False) -> None:
        self.requests = []
        self.fail = fail

    async def handle(self, session, request) -> None:
        self.requests.append((session, request))
        if self.fail:
            raise RuntimeError("private implementation detail")
        await session.send(Error(Operation.GET_NEW_MESSAGES, ErrorCode.BUSY, "later"))


def run(awaitable):
    return asyncio.run(awaitable)


def make_session(*, clock=lambda: 1.0, handler=None):
    sent = []

    async def send(frame):
        sent.append(frame)

    registry = SessionRegistry(clock=clock)
    session = ApplicationSession(
        callsign="N0CALL",
        session_id="connection-1",
        registry=registry,
        send=send,
        command_handler=handler or RecordingHandler(),
    )
    return session, registry, sent


def test_creation_is_transport_independent_and_initially_inactive():
    session, registry, sent = make_session()

    assert session.callsign == "N0CALL"
    assert session.session_id == "connection-1"
    assert session.state is SessionState.CREATED
    assert run(registry.get(session.session_id)) is None
    assert sent == []


def test_activation_registers_and_close_removes_idempotently():
    async def scenario():
        session, registry, _ = make_session()
        await session.activate()
        active = await registry.get(session.session_id)
        assert active is not None
        assert active.callsign == session.callsign
        assert session.state is SessionState.ACTIVE

        await session.close()
        await session.close()
        assert session.state is SessionState.CLOSED
        assert await registry.get(session.session_id) is None

    run(scenario())


def test_incoming_request_reaches_seam_and_response_uses_send_callback():
    async def scenario():
        handler = RecordingHandler()
        session, _, sent = make_session(handler=handler)
        await session.activate()
        request = GetNewMessages(7, 2)

        await session.receive(encode_frame(request))

        assert handler.requests == [(session, request)]
        assert decode_frame(sent[0]) == Error(
            Operation.GET_NEW_MESSAGES, ErrorCode.BUSY, "later"
        )

    run(scenario())


def test_incoming_and_server_delivery_refresh_registry_activity():
    async def scenario():
        ticks = iter((1.0, 2.0, 3.0, 4.0))
        session, registry, sent = make_session(clock=lambda: next(ticks))
        await session.activate()
        assert (await registry.get(session.session_id)).last_activity == 1.0

        await session.receive(encode_frame(GetNewMessages(0, 1)))
        assert (await registry.get(session.session_id)).last_activity == 3.0

        event = encode_frame(Error(Operation.GET_NEW_MESSAGES, ErrorCode.BUSY, "event"))
        assert await registry.deliver(session.session_id, event)
        assert sent[-1] == event
        assert (await registry.get(session.session_id)).last_activity == 4.0

    run(scenario())


def test_closed_session_rejects_requests_and_cannot_reactivate():
    async def scenario():
        handler = RecordingHandler()
        session, _, _ = make_session(handler=handler)
        await session.activate()
        await session.close()

        with pytest.raises(SessionClosedError):
            await session.receive(encode_frame(GetNewMessages(0, 1)))
        with pytest.raises(SessionClosedError):
            await session.activate()
        assert handler.requests == []

    run(scenario())


def test_handler_failure_is_isolated_and_session_remains_registered():
    async def scenario():
        session, registry, sent = make_session(handler=RecordingHandler(fail=True))
        await session.activate()

        await session.receive(encode_frame(GetNewMessages(0, 1)))

        response = decode_frame(sent[0])
        assert response == Error(
            Operation.GET_NEW_MESSAGES,
            ErrorCode.INTERNAL_ERROR,
            "request handling failed",
        )
        assert "private" not in response.detail
        assert await registry.get(session.session_id) is not None

    run(scenario())


def test_malformed_request_reports_protocol_error_without_dispatch():
    async def scenario():
        handler = RecordingHandler()
        session, registry, sent = make_session(handler=handler)
        await session.activate()

        await session.receive(bytes((1, Operation.GET_NEW_MESSAGES, 0, 8)))

        response = decode_frame(sent[0])
        assert isinstance(response, Error)
        assert response.error_code is ErrorCode.INVALID_FRAME
        assert handler.requests == []
        assert await registry.get(session.session_id) is not None

    run(scenario())
