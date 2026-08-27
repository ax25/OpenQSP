"""Internet API v1 contract and acceptance tests."""

import concurrent.futures

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from openqsp.api import create_api  # noqa: E402
from openqsp.storage import AccountStore, Database, MessageStore  # noqa: E402


@pytest.fixture
def api(tmp_path):
    database = Database(tmp_path / "api.db")
    database.initialize()
    accounts = AccountStore(database)
    for callsign in ("EA3GNU", "EA3ABC", "EA3XYZ"):
        accounts.create_account(callsign, "password")
    app = create_api(
        accounts=accounts, messages=MessageStore(database), secret="test-secret"
    )
    with TestClient(app) as client:
        yield client


def login(api, callsign="EA3GNU", password="password"):
    response = api.post(
        "/api/v1/auth/login", json={"callsign": callsign, "password": password}
    )
    return response, {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_authentication_and_me(api):
    response, headers = login(api, "ea3gnu")
    assert response.status_code == 200
    assert api.get("/api/v1/me", headers=headers).json() == {"callsign": "EA3GNU"}
    wrong = api.post(
        "/api/v1/auth/login", json={"callsign": "EA3GNU", "password": "wrong"}
    )
    unknown = api.post(
        "/api/v1/auth/login", json={"callsign": "N0NONE", "password": "wrong"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert api.get("/api/v1/me").json()["error"]["code"] == "invalid_token"
    assert (
        api.get("/api/v1/me", headers={"Authorization": "Bearer bad"}).status_code
        == 401
    )


def test_send_visibility_authorization_filter_and_idempotency(api):
    _, gnu = login(api)
    _, abc = login(api, "EA3ABC")
    _, xyz = login(api, "EA3XYZ")
    first = api.post(
        "/api/v1/messages",
        headers={**gnu, "Idempotency-Key": "one"},
        json={"to": "ea3abc", "body": "Radio test"},
    )
    repeat = api.post(
        "/api/v1/messages",
        headers={**gnu, "Idempotency-Key": "one"},
        json={"to": "EA3ABC", "body": "Radio test"},
    )
    assert first.status_code == repeat.status_code == 201
    assert first.json() == repeat.json()
    message_id = first.json()["message"]["id"]
    assert len(api.get("/api/v1/messages", headers=gnu).json()["messages"]) == 1
    assert len(api.get("/api/v1/messages", headers=abc).json()["messages"]) == 1
    assert (
        len(api.get("/api/v1/messages?with=EA3GNU", headers=abc).json()["messages"])
        == 1
    )
    assert api.get(f"/api/v1/messages/{message_id}", headers=xyz).status_code == 404
    conflict = api.post(
        "/api/v1/messages",
        headers={**gnu, "Idempotency-Key": "one"},
        json={"to": "EA3ABC", "body": "different"},
    )
    assert conflict.status_code == 409


def test_validation_sender_spoof_and_pagination(api):
    _, headers = login(api)
    spoof = api.post(
        "/api/v1/messages",
        headers=headers,
        json={"from": "EA3XYZ", "to": "EA3ABC", "body": "x"},
    )
    assert spoof.status_code == 422
    assert (
        api.post(
            "/api/v1/messages", headers=headers, json={"to": "bad", "body": "x"}
        ).status_code
        == 422
    )
    assert (
        api.post(
            "/api/v1/messages",
            headers=headers,
            json={"to": "EA3ABC", "body": "x" * 209},
        ).json()["error"]["code"]
        == "message_too_long"
    )
    for number in range(3):
        api.post(
            "/api/v1/messages",
            headers=headers,
            json={"to": "EA3ABC", "body": str(number)},
        )
    page = api.get("/api/v1/messages?limit=2", headers=headers).json()
    assert len(page["messages"]) == 2 and page["next_cursor"]
    assert (
        len(
            api.get(
                "/api/v1/messages?limit=2&cursor=" + page["next_cursor"],
                headers=headers,
            ).json()["messages"]
        )
        == 1
    )


def test_sync_isolation_advancement_and_invalid_cursor(api):
    _, gnu = login(api)
    _, abc = login(api, "EA3ABC")
    initial = api.get("/api/v1/sync", headers=abc).json()
    assert initial["messages"] == []
    api.post("/api/v1/messages", headers=gnu, json={"to": "EA3ABC", "body": "missed"})
    changed = api.get("/api/v1/sync?cursor=" + initial["cursor"], headers=abc).json()
    assert [x["body"] for x in changed["messages"]] == ["missed"]
    assert (
        api.get("/api/v1/sync?cursor=" + changed["cursor"], headers=abc).json()[
            "messages"
        ]
        == []
    )
    assert (
        api.get("/api/v1/sync?cursor=" + changed["cursor"], headers=gnu).status_code
        == 400
    )
    assert api.get("/api/v1/sync?cursor=bad", headers=abc).status_code in (400, 401)


def test_concurrent_idempotency(api):
    _, headers = login(api)

    def submit(_):
        return api.post(
            "/api/v1/messages",
            headers={**headers, "Idempotency-Key": "parallel"},
            json={"to": "EA3ABC", "body": "once"},
        ).json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(8)))
    assert all(result == results[0] for result in results)
    assert len(api.get("/api/v1/messages", headers=headers).json()["messages"]) == 1


def test_acceptance_websocket_disconnect_and_sync_recovery(api):
    _, gnu = login(api)
    abc_login, abc = login(api, "EA3ABC")
    token = abc_login.json()["access_token"]
    cursor = api.get("/api/v1/sync", headers=abc).json()["cursor"]
    with api.websocket_connect(f"/api/v1/ws?token={token}") as socket:
        sent = api.post(
            "/api/v1/messages",
            headers={**gnu, "Idempotency-Key": "ws"},
            json={"to": "EA3ABC", "body": "Radio test"},
        )
        event = socket.receive_json()
        assert sent.status_code == 201 and event["type"] == "message.created"
        assert event["data"] == sent.json()["message"]
    api.post("/api/v1/messages", headers=gnu, json={"to": "EA3ABC", "body": "offline"})
    recovered = api.get("/api/v1/sync?cursor=" + cursor, headers=abc).json()
    assert [x["body"] for x in recovered["messages"]] == ["Radio test", "offline"]
    assert (
        api.get("/api/v1/sync?cursor=" + recovered["cursor"], headers=abc).json()[
            "messages"
        ]
        == []
    )
