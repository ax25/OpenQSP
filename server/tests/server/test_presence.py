"""MVP authoritative presence and delivery-router rules."""

from openqsp.protocol import Message
from openqsp.server import ActiveTransport, DeliveryRouter, PresenceRegistry


def message() -> Message:
    return Message(1, 100, "K1ABC", "EA3GNU", "hello")


def test_absent_recipient_stays_pending_without_delivery_attempt() -> None:
    router = DeliveryRouter()
    attempted = []
    router.websocket_delivery = lambda value, session: attempted.append(value) or True
    router.aprs_delivery = lambda value, endpoint: attempted.append(value) or True

    assert router.route(message()) is None
    assert attempted == []


def test_active_websocket_is_selected() -> None:
    router = DeliveryRouter()
    delivered = []
    router.websocket_delivery = lambda value, session: delivered.append(session) or True
    router.presence.set_websocket("EA3GNU", "session-1")

    assert router.route(message()) is ActiveTransport.WEBSOCKET
    assert delivered == ["session-1"]


def test_new_websocket_replaces_old_and_late_close_cannot_clear_it() -> None:
    presence = PresenceRegistry()
    presence.set_websocket("EA3GNU", "old")
    presence.set_websocket("EA3GNU", "new")

    assert presence.clear_websocket("EA3GNU", "old") is False
    assert presence.get("EA3GNU").session_id == "new"
    assert presence.clear_websocket("EA3GNU", "new") is True
    assert presence.get("EA3GNU") is None


def test_aprs_is_explicit_and_selected_with_endpoint() -> None:
    router = DeliveryRouter()
    endpoints = []
    router.aprs_delivery = lambda value, endpoint: endpoints.append(endpoint) or True
    router.presence.set_aprs("EA3GNU", "EA3GNU-7")

    assert router.route(message()) is ActiveTransport.APRS
    assert endpoints == ["EA3GNU-7"]


def test_transport_changes_are_authoritative_in_both_directions() -> None:
    presence = PresenceRegistry()
    presence.set_aprs("EA3GNU", "EA3GNU-7")
    presence.set_websocket("EA3GNU", "web")
    assert presence.get("EA3GNU").active_transport is ActiveTransport.WEBSOCKET
    assert presence.get("EA3GNU").aprs_endpoint is None

    presence.set_aprs("EA3GNU", "EA3GNU-9")
    current = presence.get("EA3GNU")
    assert current.active_transport is ActiveTransport.APRS
    assert current.session_id is None
    assert current.aprs_endpoint == "EA3GNU-9"
