"""Message delivery/read status API and realtime contract tests."""

import time

import pytest
from fastapi.testclient import TestClient
from openqsp.api import create_api
from openqsp.server import ServerCore
from openqsp.storage import AccountStore, Database, MessageStore


class RecordingSocket:
    """Minimal async socket used to record EventHub payloads deterministically."""

    def __init__(self):
        self.events = []

    async def send_json(self, payload):
        self.events.append(payload)


@pytest.fixture
def api(tmp_path):
    database = Database(tmp_path / "status.db")
    database.initialize()
    accounts = AccountStore(database)
    for callsign in ("EA3GNU", "EA3ABC"):
        accounts.create_account(callsign, "password")
    messages = MessageStore(database)
    core = ServerCore(message_store=messages)
    app = create_api(
        accounts=accounts,
        messages=messages,
        core=core,
        secret="test-secret",
    )
    app.state.core = core
    with TestClient(app) as client:
        yield client


def login(api, callsign):
    response = api.post(
        "/api/v1/auth/login",
        json={"callsign": callsign, "password": "password"},
    )
    return response.json()["access_token"], {
        "Authorization": f"Bearer {response.json()['access_token']}"
    }


def send(api, headers, key="status"):
    return api.post(
        "/api/v1/messages",
        headers={**headers, "Idempotency-Key": key},
        json={"to": "EA3ABC", "body": "status test"},
    )


def wait_for_events(socket, count, timeout=1.0):
    """Bounded wait for callbacks scheduled onto the TestClient event loop."""
    deadline = time.monotonic() + timeout
    while len(socket.events) < count and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(socket.events) >= count


def test_message_status_is_stored_then_delivered_then_read(api):
    _, gnu = login(api, "EA3GNU")
    _, abc = login(api, "EA3ABC")

    created = send(api, gnu).json()["message"]
    assert created["delivery_status"] == "stored"
    assert created["delivered_at"] is None

    core = api.app.state.core
    core.mark_aprs_pending("EA3ABC", 1)
    core.mark_aprs_delivered("EA3ABC", 1)

    delivered = api.get(
        f"/api/v1/messages/{created['id']}", headers=gnu
    ).json()["message"]
    assert delivered["delivery_status"] == "delivered"
    assert delivered["delivered_at"] is not None

    read = api.post("/api/v1/conversations/EA3GNU/read", headers=abc)
    assert read.status_code == 200

    reconstructed = api.get(
        "/api/v1/messages?with=EA3ABC", headers=gnu
    ).json()["messages"]
    assert reconstructed[0]["delivery_status"] == "read"
    assert reconstructed[0]["delivered_at"] == delivered["delivered_at"]


def test_websocket_delivery_is_persisted_and_events_are_ordered(api):
    _, gnu = login(api, "EA3GNU")
    login(api, "EA3ABC")
    sender_socket = RecordingSocket()
    recipient_socket = RecordingSocket()
    events = api.app.state.events
    events.connections["EA3GNU"].add(sender_socket)
    events.connections["EA3ABC"].add(recipient_socket)
    events.sessions["sender-session"] = sender_socket
    events.sessions["recipient-session"] = recipient_socket
    events.router.presence.set_websocket("EA3GNU", "sender-session")
    events.router.presence.set_websocket("EA3ABC", "recipient-session")

    try:
        created = send(api, gnu, "internet-delivery").json()["message"]
        wait_for_events(sender_socket, 2)
        wait_for_events(recipient_socket, 1)
    finally:
        events.remove("EA3GNU", sender_socket, "sender-session")
        events.remove("EA3ABC", recipient_socket, "recipient-session")

    sender_created, delivered = sender_socket.events
    recipient_created = recipient_socket.events[0]
    assert sender_created["type"] == "message.created"
    assert sender_created["data"]["id"] == created["id"]
    assert recipient_created == sender_created
    assert delivered["type"] == "message.delivered"
    assert delivered["data"]["id"] == created["id"]

    reconstructed = api.get(
        f"/api/v1/messages/{created['id']}", headers=gnu
    ).json()["message"]
    assert reconstructed["delivery_status"] == "delivered"
    assert reconstructed["delivered_at"] == delivered["data"]["delivered_at"]


def test_mark_read_emits_one_cursor_event_only_when_read_cursor_advances(api):
    _, gnu = login(api, "EA3GNU")
    _, abc = login(api, "EA3ABC")
    created = send(api, gnu, "read-event").json()["message"]
    socket = RecordingSocket()
    events = api.app.state.events
    events.connections["EA3GNU"].add(socket)
    events.sessions["read-session"] = socket
    events.router.presence.set_websocket("EA3GNU", "read-session")

    try:
        first = api.post("/api/v1/conversations/EA3GNU/read", headers=abc)
        assert first.status_code == 200
        read_events = [
            event for event in socket.events if event["type"] == "message.read"
        ]
        assert read_events == [
            {
                "type": "message.read",
                "data": {
                    "peer": "EA3ABC",
                    "last_read_message_id": created["id"],
                },
            }
        ]

        # Repeating the same read operation is idempotent and must not advance
        # the durable cursor or create a second realtime event.
        second = api.post("/api/v1/conversations/EA3GNU/read", headers=abc)
        assert second.json() == first.json()
        assert len(
            [event for event in socket.events if event["type"] == "message.read"]
        ) == 1
    finally:
        events.remove("EA3GNU", socket, "read-session")


def test_conversation_last_message_projects_read_status(api):
    _, gnu = login(api, "EA3GNU")
    _, abc = login(api, "EA3ABC")
    send(api, gnu, "conversation-status")

    api.post("/api/v1/conversations/EA3GNU/read", headers=abc)
    conversations = api.get("/api/v1/conversations", headers=gnu).json()[
        "conversations"
    ]
    assert conversations[0]["peer"] == "EA3ABC"
    assert conversations[0]["last_message"]["delivery_status"] == "read"
