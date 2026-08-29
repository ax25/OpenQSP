"""Authoritative single-WebSocket lifecycle tests."""

import asyncio

from openqsp.api import EventHub
from openqsp.server import ActiveTransport


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
