"""Integrated Milestone 3 conformance workflows through encoded Core frames."""

from openqsp.protocol import (
    Ack, AckStatus, Bulletin, BulletinHeader, End, Error, ErrorCode,
    GetBulletin, GetNewBulletins, GetNewMessages, Message, Operation,
    SendMessage, decode_frame, encode_frame,
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
    original = SendMessage(1001, 1_786_200_000, "EA3GNU", "Hello")

    assert not hasattr(original, "author")
    assert exchange(core, "K1ABC", original) == [Ack(1001, AckStatus.STORED)]
    # Simulate losing that response and submitting the exact encoded request again.
    assert exchange(core, "K1ABC", original) == [
        Ack(1001, AckStatus.ALREADY_STORED)
    ]
    assert exchange(
        core, "K1ABC", SendMessage(1001, 1_786_200_000, "EA3GNU", "changed")
    ) == [Ack(1001, AckStatus.CONFLICT)]
    assert exchange(
        core, "K1ABC", SendMessage(1002, 1_786_200_001, "N0CALL", "private")
    ) == [Ack(1002, AckStatus.STORED)]

    ea3gnu = exchange(core, "EA3GNU", GetNewMessages(0, 20))
    n0call = exchange(core, "N0CALL", GetNewMessages(0, 20))
    outsider = exchange(core, "F4XYZ", GetNewMessages(0, 20))
    assert ea3gnu == [
        Message(1, 1001, 1_786_200_000, "K1ABC", "EA3GNU", "Hello"),
        End(Operation.GET_NEW_MESSAGES, 1, 1, False),
    ]
    assert n0call == [
        Message(2, 1002, 1_786_200_001, "K1ABC", "N0CALL", "private"),
        End(Operation.GET_NEW_MESSAGES, 1, 2, False),
    ]
    assert outsider == [End(Operation.GET_NEW_MESSAGES, 0, 0, False)]


def test_incremental_sync_pagination_and_end_cursor_safety(tmp_path):
    core, _ = node(tmp_path / "node.db")
    for message_id in range(1, 5):
        assert exchange(
            core,
            "K1ABC",
            SendMessage(message_id, 100 + message_id, "EA3GNU", f"message {message_id}"),
        ) == [Ack(message_id, AckStatus.STORED)]

    first = exchange(core, "EA3GNU", GetNewMessages(0, 2))
    assert [item.message_id for item in first[:-1]] == [1, 2]
    assert first[-1] == End(Operation.GET_NEW_MESSAGES, 2, 2, True)
    # Item sequences are not cursors: only the terminating END authorizes progress.
    assert all(not hasattr(item, "next_since") for item in first[:-1])
    cursor = first[-1].next_since
    assert cursor == 2

    second = exchange(core, "EA3GNU", GetNewMessages(cursor, 2))
    assert [item.message_id for item in second[:-1]] == [3, 4]
    assert second[-1] == End(Operation.GET_NEW_MESSAGES, 2, 4, False)
    assert {item.message_id for item in first[:-1] + second[:-1]} == {1, 2, 3, 4}

    assert exchange(core, "EA3GNU", GetNewMessages(4, 20)) == [
        End(Operation.GET_NEW_MESSAGES, 0, 4, False)
    ]
    exchange(core, "K1ABC", SendMessage(5, 105, "EA3GNU", "message 5"))
    assert exchange(core, "EA3GNU", GetNewMessages(4, 20)) == [
        Message(5, 5, 105, "K1ABC", "EA3GNU", "message 5"),
        End(Operation.GET_NEW_MESSAGES, 1, 5, False),
    ]


def test_public_bulletins_headers_full_objects_and_missing_id(tmp_path):
    core, store = node(tmp_path / "node.db")
    for bulletin_id in (50, 51):
        store.store_bulletin(
            bulletin_id=bulletin_id, created_at=200 + bulletin_id,
            author="EA9SRC", title=f"Bulletin {bulletin_id}",
            body=f"Full body {bulletin_id}",
        )

    headers = exchange(core, "EA3GNU", GetNewBulletins(0, 20))
    assert headers == [
        BulletinHeader(1, 50, 250, "EA9SRC", "Bulletin 50"),
        BulletinHeader(2, 51, 251, "EA9SRC", "Bulletin 51"),
        End(Operation.GET_NEW_BULLETINS, 2, 2, False),
    ]
    assert all(not hasattr(header, "body") for header in headers[:-1])
    assert exchange(core, "EA3GNU", GetBulletin(50)) == [
        Bulletin(50, 250, "EA9SRC", "Bulletin 50", "Full body 50")
    ]
    assert exchange(core, "K1ABC", GetBulletin(50)) == exchange(
        core, "F4XYZ", GetBulletin(50)
    )
    assert exchange(core, "K1ABC", GetBulletin(999)) == [
        Error(Operation.GET_BULLETIN, ErrorCode.NOT_FOUND, "bulletin not found")
    ]


def test_restart_preserves_messages_retries_sync_and_bulletins(tmp_path):
    path = tmp_path / "restart.db"
    first, bulletins = node(path)
    request = SendMessage(80, 800, "EA3GNU", "durable")
    assert exchange(first, "K1ABC", request) == [Ack(80, AckStatus.STORED)]
    bulletins.store_bulletin(
        bulletin_id=81, created_at=801, author="EA9SRC", title="Durable", body="Still here"
    )

    restarted, _ = node(path)
    assert exchange(restarted, "K1ABC", request) == [
        Ack(80, AckStatus.ALREADY_STORED)
    ]
    assert exchange(restarted, "EA3GNU", GetNewMessages(0, 20))[0] == Message(
        1, 80, 800, "K1ABC", "EA3GNU", "durable"
    )
    assert exchange(restarted, "EA3GNU", GetBulletin(81)) == [
        Bulletin(81, 801, "EA9SRC", "Durable", "Still here")
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
    valid = bytearray(encode_frame(SendMessage(90, 900, "EA3GNU", "valid")))
    valid[16] = 1
    invalid = core.handle_frame("K1ABC", bytes(valid))
    assert [decode_frame(frame) for frame in invalid] == [Ack(90, AckStatus.INVALID)]

    assert exchange(core, "K1ABC", SendMessage(91, 901, "EA3GNU", "healthy")) == [
        Ack(91, AckStatus.STORED)
    ]
    assert exchange(core, "EA3GNU", GetNewMessages(0, 20))[0].message_id == 91
