"""Focused synchronous client transport tests."""

from contextlib import contextmanager
import socket
import threading
from pathlib import Path
import sys

import pytest

TOOLS_ROOT = Path(__file__).parents[3] / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from client_sim import (  # noqa: E402
    ConnectionFailed,
    DevelopmentClient,
    DevelopmentHandshakeError,
    TcpTransport,
    TransportError,
    TruncatedResponseError,
)
from openqsp.protocol import (  # noqa: E402
    Stored,
    End,
    GetNewMessages,
    Message,
    Operation,
    SendMessage,
    encode_frame,
)


@contextmanager
def _scripted_server(chunks, *, handshake=b"OK\n"):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]

    def serve():
        connection, _ = listener.accept()
        with connection:
            line = b""
            while not line.endswith(b"\n"):
                line += connection.recv(1)
            connection.sendall(handshake)
            if handshake == b"OK\n":
                header = connection.recv(4)
                remaining = header[3] if len(header) == 4 else 0
                while remaining:
                    received = connection.recv(remaining)
                    if not received:
                        break
                    remaining -= len(received)
                for chunk in chunks:
                    connection.sendall(chunk)
        listener.close()

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        yield port
    finally:
        thread.join(timeout=2)
        listener.close()


def test_successful_handshake_one_response_and_fragmented_reads():
    response = encode_frame(Stored())
    with _scripted_server([bytes((byte,)) for byte in response]) as port:
        result = DevelopmentClient(TcpTransport("127.0.0.1", port), "K1ABC").request(
            SendMessage(20, "N0CALL", "hello")
        )
    assert result == [Stored()]


def test_multiple_response_frames_are_read_through_end():
    responses = [
        Message(1, 20, "K1ABC", "N0CALL", "hello"),
        End(Operation.GET_NEW_MESSAGES, 1, 1, False),
    ]
    with _scripted_server([b"".join(map(encode_frame, responses))]) as port:
        result = DevelopmentClient(TcpTransport("127.0.0.1", port), "N0CALL").request(
            GetNewMessages(0, 5)
        )
    assert result == responses


def test_rejected_development_handshake_is_a_transport_error():
    with _scripted_server([], handshake=b"ERROR\n") as port:
        with pytest.raises(DevelopmentHandshakeError):
            TcpTransport("127.0.0.1", port).exchange(
                "BAD", encode_frame(GetNewMessages(0, 5))
            )


@pytest.mark.parametrize("partial", [b"", b"\x01\x43", b"\x01\x43\x00\x05abc"])
def test_disconnect_and_truncated_frames_are_distinct_transport_errors(partial):
    with _scripted_server([partial]) as port:
        expected = ConnectionFailed if not partial else TruncatedResponseError
        with pytest.raises(expected) as caught:
            TcpTransport("127.0.0.1", port).exchange(
                "K1ABC", encode_frame(GetNewMessages(0, 5))
            )
    assert isinstance(caught.value, TransportError)


def test_connection_failure_is_not_an_openqsp_error():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    with pytest.raises(ConnectionFailed):
        TcpTransport("127.0.0.1", port).exchange(
            "K1ABC", encode_frame(GetNewMessages(0, 5))
        )
