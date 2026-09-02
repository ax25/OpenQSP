from __future__ import annotations

from openqsp.protocol import SendMessage, encode_frame
from openqsp.server import ServerCore
from openqsp.storage import Database, MessageStore
from openqsp.transport.aprs import (
    AdapterConfig,
    SelectiveBurstAPRSAdapter,
    parse_stored,
)
from openqsp.transport.aprs.carriage import fragment_frame_v2


def test_send_message_success_uses_compact_s2_result(tmp_path) -> None:
    database = Database(tmp_path / "node.db")
    database.initialize()
    core = ServerCore(message_store=MessageStore(database))
    adapter = SelectiveBurstAPRSAdapter(
        core,
        config=AdapterConfig(min_interval=0),
    )
    frame = encode_frame(
        SendMessage(
            created_at=1_700_000_000,
            recipient="EA3BBB",
            body="compact durable result",
        )
    )
    fragments = fragment_frame_v2(frame, "001")

    for fragment in fragments[:-1]:
        assert adapter.receive("EA3AAA", fragment.body, now=0) == "fragment"
    assert adapter.receive("EA3AAA", fragments[-1].body, now=0) == "completed"

    result = adapter.poll(now=0)

    assert len(result) == 1
    assert result[0].body.startswith("S2")
    assert parse_stored(result[0].body) == "001"
    assert adapter.queued_count == 0
    assert adapter.pending_count == 0


def test_compact_s2_is_replayed_without_second_core_write(tmp_path) -> None:
    database = Database(tmp_path / "node.db")
    database.initialize()
    store = MessageStore(database)
    core = ServerCore(message_store=store)
    adapter = SelectiveBurstAPRSAdapter(
        core,
        config=AdapterConfig(min_interval=0),
    )
    frame = encode_frame(
        SendMessage(
            created_at=1_700_000_000,
            recipient="EA3BBB",
            body="retry-safe",
        )
    )
    fragments = fragment_frame_v2(frame, "002")

    for fragment in fragments:
        adapter.receive("EA3AAA", fragment.body, now=0)
    first = adapter.poll(now=0)
    assert len(first) == 1 and parse_stored(first[0].body) == "002"

    for fragment in fragments:
        disposition = adapter.receive("EA3AAA", fragment.body, now=1)
    second = adapter.poll(now=1)

    assert disposition == "replayed"
    assert len(second) == 1 and parse_stored(second[0].body) == "002"
    page = store.get_new_messages(callsign="EA3BBB", since=0, limit=20)
    assert len(page.messages) == 1
