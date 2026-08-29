from pathlib import Path

from openqsp.protocol import GetNewMessages, Message, decode_frame, encode_frame
from openqsp.server import ServerCore
from openqsp.storage import BulletinStore, Database, MessageStore
from openqsp.transport.aprs import AdapterConfig, APRSAdapter
from openqsp.transport.aprs.carriage import fragment_frame, parse_fragment
from openqsp.transport.aprs.state import Reassembler


def _core(path: Path) -> tuple[ServerCore, MessageStore]:
    database = Database(path)
    database.initialize()
    messages = MessageStore(database, clock=lambda: 10)
    core = ServerCore(
        message_store=messages,
        bulletin_store=BulletinStore(database, clock=lambda: 10),
    )
    return core, messages


def _deliver_request(
    adapter: APRSAdapter,
    peer: str,
    frame: bytes,
    transaction_id: str,
    *,
    now: float,
) -> None:
    for index, fragment in enumerate(fragment_frame(frame, transaction_id)):
        disposition = adapter.receive(
            peer,
            fragment.body + f"{{{index:02X}",
            now=now,
        )
    assert disposition == "completed"


def _receive_one_response_frame(
    adapter: APRSAdapter,
    peer: str,
    *,
    now: float,
) -> bytes:
    reassembler = Reassembler()
    for _ in range(64):
        packets = adapter.poll(now=now)
        for packet in packets:
            if packet.is_ack or packet.destination != peer:
                continue
            fragment = parse_fragment(packet.body)
            adapter.receive(peer, f"ack{fragment.message_id}", now=now)
            complete = reassembler.add("OPENQSP", fragment, now)
            if complete is not None:
                return complete
    raise AssertionError("response frame was not completed")


def _delivery_status(
    messages: MessageStore,
    recipient: str,
    sequence: int,
) -> str:
    with messages._database.connect() as connection:
        row = connection.execute(
            """SELECT status FROM deliveries
               WHERE recipient=? AND mailbox_sequence=? AND transport='aprs'""",
            (recipient, sequence),
        ).fetchone()
    assert row is not None
    return row["status"]


def test_get_new_messages_stops_entire_batch_after_fragment_failure(
    tmp_path: Path,
) -> None:
    core, messages = _core(tmp_path / "sync-abort.sqlite")
    sequences = [
        messages.store_message(
            created_at=index,
            author="EA3AAA",
            recipient="EA3BBB",
            body=f"message {index}",
        )
        for index in range(1, 4)
    ]
    peer = "EA3BBB-10"
    adapter = APRSAdapter(
        core,
        config=AdapterConfig(min_interval=0, ack_timeout=1, max_attempts=1),
    )

    _deliver_request(
        adapter,
        peer,
        encode_frame(GetNewMessages(0, 20)),
        "ABC",
        now=0,
    )

    first_frame = _receive_one_response_frame(adapter, peer, now=0)
    first = decode_frame(first_frame)
    assert isinstance(first, Message)
    assert first.sequence == sequences[0]
    assert _delivery_status(messages, "EA3BBB", sequences[0]) == "delivered"

    second_packets = [
        packet
        for packet in adapter.poll(now=0)
        if not packet.is_ack and packet.destination == peer
    ]
    assert len(second_packets) == 1
    second_fragment = parse_fragment(second_packets[0].body)
    assert second_fragment.index == 0

    # Do not ACK the second message. Exhausting its retry budget must abort the
    # whole GET_NEW_MESSAGES response: no later MESSAGE and no END may remain.
    assert adapter.poll(now=1) == []
    assert adapter.queued_count == 0
    assert adapter.pending_count == 0
    assert adapter.poll(now=2) == []

    assert _delivery_status(messages, "EA3BBB", sequences[1]) == "failed"
    assert _delivery_status(messages, "EA3BBB", sequences[2]) == "failed"
