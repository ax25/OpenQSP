"""Tests for the local logical OpenQSP client simulator."""

from contextlib import redirect_stderr, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path

from openqsp.protocol import End, Message, Operation


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


def test_local_cli_workflow_persists_across_invocations(tmp_path) -> None:
    common = ("--db", str(tmp_path / "node.db"))
    sent = run(
        *common, "--callsign", "K1ABC", "send-message", "--to", "EA3GNU",
        "--id", "1001", "--timestamp", "1786200000", "--body", "Hello",
    )
    received = run(
        *common, "--callsign", "EA3GNU", "get-new-messages",
        "--since", "0", "--max", "20",
    )

    assert sent == (0, "ACK\n  object_id: 1001\n  status: STORED\n\n", "")
    assert received[0] == 0 and received[2] == ""
    assert "message_id: 1001" in received[1]
    assert "author: K1ABC" in received[1]
    assert "recipient: EA3GNU" in received[1]
    assert "next_since: 1" in received[1]


def test_development_seed_then_public_bulletin_operations(tmp_path) -> None:
    common = ("--db", str(tmp_path / "node.db"), "--callsign", "EA9SRC")
    seeded = run(
        *common, "seed-bulletin", "--id", "123", "--timestamp", "1786200001",
        "--title", "News", "--body", "Complete bulletin",
    )
    headers = run(
        "--db", str(tmp_path / "node.db"), "--callsign", "EA3GNU",
        "get-new-bulletins", "--since", "0", "--max", "20",
    )
    bulletin = run(
        "--db", str(tmp_path / "node.db"), "--callsign", "K1ABC",
        "get-bulletin", "--id", "123",
    )

    assert seeded[0] == 0 and "DEVELOPMENT SEED" in seeded[1]
    assert "BULLETIN_HEADER" in headers[1] and "title: News" in headers[1]
    assert "body:" not in headers[1]
    assert "BULLETIN\n" in bulletin[1] and "body: Complete bulletin" in bulletin[1]


def test_cursor_helper_requires_matching_terminal_end() -> None:
    item = Message(1, 10, 20, "K1ABC", "EA3GNU", "body")
    end = End(Operation.GET_NEW_MESSAGES, 1, 1, False)

    assert client_sim.completed_cursor([item], Operation.GET_NEW_MESSAGES) is None
    assert client_sim.completed_cursor([item, end], Operation.GET_NEW_MESSAGES) == 1
    assert client_sim.completed_cursor([item, end], Operation.GET_NEW_BULLETINS) is None
