"""Message delivery/read status API and realtime contract tests."""

import pytest
from fastapi.testclient import TestClient
from openqsp.api import create_api
from openqsp.server import ServerCore
from openqsp.storage import AccountStore, Database, MessageStore


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
    gnu_token, gnu = login(api, "EA3GNU")
    abc_token, _ = login(api, "EA3ABC")

    with (
        api.websocket_connect(f"/api/v1/ws?token={gnu_token}") as sender_socket,
        api.websocket_connect(f"/api/v1/ws?token={abc_token}") as recipient_socket,
    ):
        created = send(api, gnu, "internet-delivery").json()["message"]

        sender_created = sender_socket.receive_json()
        recipient_created = recipient_socket.receive_json()
        delivered = sender_socket.receive_json()

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
    gnu_token, gnu = login(api, "EA3GNU")
    _, abc = login(api, "EA3ABC")
    created = send(api, gnu, "read-event").json()["message"]

    with api.websocket_connect(f"/api/v1/ws?token={gnu_token}") as socket:
        first = api.post("/api/v1/conversations/EA3GNU/read", headers=abc)
        assert first.status_code == 200
        event = socket.receive_json()
        assert event == {
            "type": "message.read",
            "data": {
                "peer": "EA3ABC",
                "last_read_message_id": created["id"],
            },
        }

        # Repeating the same read operation is idempotent and must not advance
        # the durable cursor or create a second realtime event.
        second = api.post("/api/v1/conversations/EA3GNU/read", headers=abc)
        assert second.json() == first.json()


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
