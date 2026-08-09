"""Tests for the local logical OpenQSP client simulator."""

from contextlib import redirect_stderr, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path

import pytest
from openqsp.protocol import (
    End,
    Message,
    Operation,
    SendMessage,
    Stored,
    encode_frame,
)

TOOL_PATH = Path(__file__).parents[3] / "tools" / "client_sim.py"
SPEC = spec_from_file_location("client_sim", TOOL_PATH)
assert SPEC and SPEC.loader
client_sim = module_from_spec(SPEC)
SPEC.loader.exec_module(client_sim)


def run(*args: str) -> tuple[int, str, str]:
    stdout, stderr = StringIO(), StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = client_sim.main(list(args))
    return result, stdout.getvalue(), stderr.getvalue()


def test_local_transport_forwards_and_returns_frames_unchanged() -> None:
    responses = [b"first", b"second"]

    class RecordingCore:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bytes]] = []

        def handle_frame(self, callsign: str, frame: bytes) -> list[bytes]:
            self.calls.append((callsign, frame))
            return responses

    core = RecordingCore()
    transport = client_sim.LocalCoreTransport(core)

    result = transport.exchange("K1ABC", b"encoded request")

    assert core.calls == [("K1ABC", b"encoded request")]
    assert result is responses


def test_development_client_encodes_and_decodes_only_outside_transport(
    monkeypatch,
) -> None:
    request = SendMessage(1786200000, "EA3GNU", "Hello")
    encoded_request = b"client encoded request"
    encoded_responses = [b"encoded response"]
    decoded_response = Stored()

    class FakeTransport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bytes]] = []

        def exchange(self, callsign: str, frame: bytes) -> list[bytes]:
            self.calls.append((callsign, frame))
            return encoded_responses

    encoded: list[object] = []
    decoded: list[bytes] = []

    def fake_encode(value):
        encoded.append(value)
        return encoded_request

    def fake_decode(frame):
        decoded.append(frame)
        return decoded_response

    monkeypatch.setattr(client_sim, "encode_frame", fake_encode)
    monkeypatch.setattr(client_sim, "decode_frame", fake_decode)
    transport = FakeTransport()

    result = client_sim.DevelopmentClient(transport, "K1ABC").request(request)

    assert encoded == [request]
    assert transport.calls == [("K1ABC", encoded_request)]
    assert decoded == encoded_responses
    assert result == [decoded_response]


def test_fake_transport_can_be_injected_without_server_core() -> None:
    response = Stored()

    class FakeTransport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bytes]] = []

        def exchange(self, callsign: str, frame: bytes) -> list[bytes]:
            self.calls.append((callsign, frame))
            return [encode_frame(response)]

    transport = FakeTransport()
    request = SendMessage(1786200000, "EA3GNU", "Hello")

    assert client_sim.DevelopmentClient(transport, "K1ABC").request(request) == [
        response
    ]
    assert transport.calls == [("K1ABC", encode_frame(request))]


def test_transport_failure_is_not_decoded_as_a_protocol_response(monkeypatch) -> None:
    class TransportFailure(Exception):
        pass

    class FailingTransport:
        def exchange(self, callsign: str, frame: bytes) -> list[bytes]:
            raise TransportFailure("delivery failed")

    decode_calls: list[bytes] = []
    monkeypatch.setattr(client_sim, "decode_frame", decode_calls.append)

    with pytest.raises(TransportFailure, match="delivery failed"):
        client_sim.DevelopmentClient(FailingTransport(), "K1ABC").request(
            SendMessage(1786200000, "EA3GNU", "Hello")
        )

    assert decode_calls == []


def test_local_cli_workflow_persists_across_invocations(tmp_path) -> None:
    common = ("--db", str(tmp_path / "node.db"))
    sent = run(
        *common, "--callsign", "K1ABC", "send-message", "--to", "EA3GNU",
"--timestamp", "1786200000", "--body", "Hello",
    )
    received = run(
        *common, "--callsign", "EA3GNU", "get-new-messages",
        "--since", "0", "--max", "20",
    )

    assert sent == (0, "STORED\n\n", "")
    assert received[0] == 0 and received[2] == ""
    assert "sequence: 1" in received[1]
    assert "author: K1ABC" in received[1]
    assert "recipient: EA3GNU" in received[1]
    assert "next_since: 1" in received[1]


def test_development_seed_then_public_bulletin_operations(tmp_path) -> None:
    common = ("--db", str(tmp_path / "node.db"), "--callsign", "EA9SRC")
    seeded = run(
        *common, "seed-bulletin", "--timestamp", "1786200001",
        "--title", "News", "--body", "Complete bulletin",
    )
    headers = run(
        "--db", str(tmp_path / "node.db"), "--callsign", "EA3GNU",
        "get-new-bulletins", "--since", "0", "--max", "20",
    )
    bulletin = run(
        "--db", str(tmp_path / "node.db"), "--callsign", "K1ABC",
        "get-bulletin", "--sequence", "1",
    )

    assert seeded[0] == 0 and "DEVELOPMENT SEED" in seeded[1]
    assert "BULLETIN_HEADER" in headers[1] and "title: News" in headers[1]
    assert "body:" not in headers[1]
    assert "BULLETIN\n" in bulletin[1] and "body: Complete bulletin" in bulletin[1]


def test_cursor_helper_requires_matching_terminal_end() -> None:
    item = Message(1, 20, "K1ABC", "EA3GNU", "body")
    end = End(Operation.GET_NEW_MESSAGES, 1, 1, False)

    assert client_sim.completed_cursor([item], Operation.GET_NEW_MESSAGES) is None
    assert client_sim.completed_cursor([item, end], Operation.GET_NEW_MESSAGES) == 1
    assert client_sim.completed_cursor([item, end], Operation.GET_NEW_BULLETINS) is None
