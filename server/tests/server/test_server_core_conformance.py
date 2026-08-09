"""Integrated Milestone 3 conformance workflows through encoded Core frames."""

from openqsp.protocol import (
    Bulletin,
    BulletinHeader,
    End,
    Error,
    ErrorCode,
    GetBulletin,
    GetNewBulletins,
    GetNewMessages,
    Message,
    Operation,
    SendMessage,
    Stored,
    decode_frame,
    encode_frame,
)
from openqsp.server import ServerCore
from openqsp.storage import BulletinStore, Database, MessageStore


def node(path):
    database = Database(path)
    database.initialize()
    bulletins = BulletinStore(database)
    return ServerCore(message_store=MessageStore(database), bulletin_store=bulletins), bulletins


def exchange(core, callsign, request):
    request_bytes = encode_frame(request)
    frames = core.handle_frame(callsign, request_bytes)
    # Every response is canonical output from the production encoder.
    assert all(frame == encode_frame(decode_frame(frame)) for frame in frames)
    return [decode_frame(frame) for frame in frames]


def test_private_identity_retry_conflict_and_mailbox_isolation(tmp_path):
    core, _ = node(tmp_path / "node.db")
    original = SendMessage(1_786_200_000, "EA3GNU", "Hello")

    assert not hasattr(original, "author")
    assert exchange(core, "K1ABC", original) == [Stored()]
    # Simulate losing that response and submitting the exact encoded request again.
    assert exchange(core, "K1ABC", original) == [
        Stored()
    ]
    assert exchange(
        core, "K1ABC", SendMessage(1_786_200_000, "EA3GNU", "changed")
    ) == [Stored()]
    assert exchange(
        core, "K1ABC", SendMessage(1_786_200_001, "N0CALL", "private")
    ) == [Stored()]

    ea3gnu = exchange(core, "EA3GNU", GetNewMessages(0, 20))
    n0call = exchange(core, "N0CALL", GetNewMessages(0, 20))
    outsider = exchange(core, "F4XYZ", GetNewMessages(0, 20))
    assert ea3gnu == [
        Message(1, 1_786_200_000, "K1ABC", "EA3GNU", "Hello"),
        Message(2, 1_786_200_000, "K1ABC", "EA3GNU", "Hello"),
        Message(3, 1_786_200_000, "K1ABC", "EA3GNU", "changed"),
        End(Operation.GET_NEW_MESSAGES, 3, 3, False),
    ]
    assert n0call == [
        Message(1, 1_786_200_001, "K1ABC", "N0CALL", "private"),
        End(Operation.GET_NEW_MESSAGES, 1, 1, False),
    ]
    assert outsider == [End(Operation.GET_NEW_MESSAGES, 0, 0, False)]


def test_incremental_sync_pagination_and_end_cursor_safety(tmp_path):
    core, _ = node(tmp_path / "node.db")
    for sequence in range(1, 5):
        assert exchange(
            core,
            "K1ABC",
            SendMessage(100 + sequence, "EA3GNU", f"message {sequence}"),
        ) == [Stored()]

    first = exchange(core, "EA3GNU", GetNewMessages(0, 2))
    assert [item.sequence for item in first[:-1]] == [1, 2]
    assert first[-1] == End(Operation.GET_NEW_MESSAGES, 2, 2, True)
    # Item sequences are not cursors: only the terminating END authorizes progress.
    assert all(not hasattr(item, "next_since") for item in first[:-1])
    cursor = first[-1].next_since
    assert cursor == 2

    second = exchange(core, "EA3GNU", GetNewMessages(cursor, 2))
    assert [item.sequence for item in second[:-1]] == [3, 4]
    assert second[-1] == End(Operation.GET_NEW_MESSAGES, 2, 4, False)
    assert {item.sequence for item in first[:-1] + second[:-1]} == {1, 2, 3, 4}

    assert exchange(core, "EA3GNU", GetNewMessages(4, 20)) == [
        End(Operation.GET_NEW_MESSAGES, 0, 4, False)
    ]
    exchange(core, "K1ABC", SendMessage(105, "EA3GNU", "message 5"))
    assert exchange(core, "EA3GNU", GetNewMessages(4, 20)) == [
        Message(5, 105, "K1ABC", "EA3GNU", "message 5"),
        End(Operation.GET_NEW_MESSAGES, 1, 5, False),
    ]


def test_public_bulletins_headers_full_objects_and_missing_id(tmp_path):
    core, store = node(tmp_path / "node.db")
    for sequence in (50, 51):
        store.store_bulletin(
            created_at=200 + sequence,
            author="EA9SRC", title=f"Bulletin {sequence}",
            body=f"Full body {sequence}",
        )

    headers = exchange(core, "EA3GNU", GetNewBulletins(0, 20))
    assert headers == [
        BulletinHeader(1, 250, "EA9SRC", "Bulletin 50"),
        BulletinHeader(2, 251, "EA9SRC", "Bulletin 51"),
        End(Operation.GET_NEW_BULLETINS, 2, 2, False),
    ]
    assert all(not hasattr(header, "body") for header in headers[:-1])
    assert exchange(core, "EA3GNU", GetBulletin(1)) == [
        Bulletin(1, 250, "EA9SRC", "Bulletin 50", "Full body 50")
    ]
    assert exchange(core, "K1ABC", GetBulletin(1)) == exchange(
        core, "F4XYZ", GetBulletin(1)
    )
    assert exchange(core, "K1ABC", GetBulletin(999)) == [
        Error(Operation.GET_BULLETIN, ErrorCode.NOT_FOUND, "bulletin not found")
    ]


def test_restart_preserves_messages_retries_sync_and_bulletins(tmp_path):
    path = tmp_path / "restart.db"
    first, bulletins = node(path)
    request = SendMessage(800, "EA3GNU", "durable")
    assert exchange(first, "K1ABC", request) == [Stored()]
    bulletins.store_bulletin(
        created_at=801, author="EA9SRC", title="Durable", body="Still here"
    )

    restarted, _ = node(path)
    assert exchange(restarted, "K1ABC", request) == [
        Stored()
    ]
    assert exchange(restarted, "EA3GNU", GetNewMessages(0, 20))[0] == Message(1, 800, "K1ABC", "EA3GNU", "durable"
    )
    assert exchange(restarted, "EA3GNU", GetBulletin(1)) == [
        Bulletin(1, 801, "EA9SRC", "Durable", "Still here")
    ]


def test_representative_malformed_frames_leave_node_usable(tmp_path):
    core, _ = node(tmp_path / "node.db")
    malformed = [
        (b"\x01\x02\x00", []),
        (b"\x02\x02\x00\x00", ErrorCode.UNSUPPORTED_VERSION),
        (b"\x01\x7f\x00\x00", ErrorCode.UNKNOWN_OPERATION),
        (b"\x01\x04\x01\x08" + b"\0" * 8, ErrorCode.INVALID_FRAME),
        (b"\x01\x02\x00\x09" + b"\0" * 8, ErrorCode.INVALID_FRAME),
    ]
    for frame, expected in malformed:
        responses = core.handle_frame("K1ABC", frame)
        if expected == []:
            assert responses == []
        else:
            assert decode_frame(responses[0]).error_code == expected

    # Recoverable nonzero ID plus malformed recipient yields ACK / INVALID.
    valid = bytearray(encode_frame(SendMessage(900, "EA3GNU", "valid")))
    valid[9] = ord("e")
    invalid = core.handle_frame("K1ABC", bytes(valid))
    assert isinstance(decode_frame(invalid[0]), Error)

    assert exchange(core, "K1ABC", SendMessage(901, "EA3GNU", "healthy")) == [
        Stored()
    ]
    assert exchange(core, "EA3GNU", GetNewMessages(0, 20))[0].sequence == 1
