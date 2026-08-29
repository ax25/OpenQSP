"""Authoritative single-WebSocket lifecycle tests."""

import asyncio

from openqsp.api import EventHub
from openqsp.protocol import GetCapabilities, encode_frame
from openqsp.server import ActiveTransport, ServerCore
from openqsp.transport.aprs import AdapterConfig, APRSAdapter
from openqsp.transport.aprs.carriage import fragment_frame


class RecordingSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.closed = []
        self.events = []

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, **kwargs) -> None:
        self.closed.append(kwargs)

    async def send_json(self, payload) -> None:
        self.events.append(payload)


def test_new_websocket_closes_and_removes_previous_session() -> None:
    async def scenario() -> None:
        hub = EventHub()
        first, second = RecordingSocket(), RecordingSocket()
        first_id = await hub.connect("EA3GNU", first)
        second_id = await hub.connect("EA3GNU", second)

        assert first.closed == [
            {"code": 4001, "reason": "superseded by a newer session"}
        ]
        assert hub.connections["EA3GNU"] == {second}
        assert first_id not in hub.sessions
        assert hub.sessions == {second_id: second}

    asyncio.run(scenario())


def test_aprs_transition_does_not_hide_old_websocket_from_replacement() -> None:
    async def scenario() -> None:
        hub = EventHub()
        first, second = RecordingSocket(), RecordingSocket()
        first_id = await hub.connect("EA3GNU", first)
        hub.router.presence.set_aprs("EA3GNU", "EA3GNU-7")

        second_id = await hub.connect("EA3GNU", second)

        assert first.closed
        assert first_id not in hub.sessions
        assert hub.connections["EA3GNU"] == {second}
        assert hub.sessions == {second_id: second}
        presence = hub.router.presence.get("EA3GNU")
        assert presence.active_transport is ActiveTransport.WEBSOCKET
        assert presence.session_id == second_id

    asyncio.run(scenario())


def test_last_accepted_aprs_operation_supersedes_websocket() -> None:
    async def scenario() -> None:
        hub = EventHub()
        socket = RecordingSocket()
        await hub.connect("EA3GNU", socket)
        adapter = APRSAdapter(
            ServerCore(),
            config=AdapterConfig(min_interval=0),
            router=hub.router,
        )
        fragment = fragment_frame(encode_frame(GetCapabilities()), "ABC")[0]

        assert adapter.receive("EA3GNU-7", fragment.body, now=0) == "completed"
        presence = hub.router.presence.get("EA3GNU")
        assert presence is not None
        assert presence.active_transport is ActiveTransport.APRS
        assert presence.aprs_endpoint == "EA3GNU-7"
        assert presence.session_id is None

    asyncio.run(scenario())


def test_late_old_disconnect_cannot_remove_new_session() -> None:
    async def scenario() -> None:
        hub = EventHub()
        first, second = RecordingSocket(), RecordingSocket()
        first_id = await hub.connect("EA3GNU", first)
        second_id = await hub.connect("EA3GNU", second)

        hub.remove("EA3GNU", first, first_id)

        assert hub.connections["EA3GNU"] == {second}
        assert hub.sessions == {second_id: second}
        assert hub.router.presence.get("EA3GNU").session_id == second_id

    asyncio.run(scenario())


def test_author_events_reach_only_current_websocket() -> None:
    async def scenario() -> None:
        hub = EventHub()
        first, second = RecordingSocket(), RecordingSocket()
        await hub.connect("EA3GNU", first)
        await hub.connect("EA3GNU", second)

        payload = {"from": "EA3GNU", "id": "message-1"}
        await hub.emit_author(payload)

        assert first.events == []
        assert second.events == [
            {"type": "message.created", "data": payload}
        ]

    asyncio.run(scenario())
