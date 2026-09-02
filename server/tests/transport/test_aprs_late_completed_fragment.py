from __future__ import annotations

from openqsp.protocol import GetCapabilities, encode_frame
from openqsp.server import ServerCore
from openqsp.transport.aprs import AdapterConfig, SelectiveBurstAPRSAdapter, parse_burst_control
from openqsp.transport.aprs.carriage import fragment_frame_v2


def test_late_final_fragment_after_completion_does_not_start_nack_loop() -> None:
    adapter = SelectiveBurstAPRSAdapter(
        ServerCore(),
        config=AdapterConfig(min_interval=0),
        repair_grace=5,
        final_fragment_grace=2,
    )
    transaction = "04G"
    fragments = fragment_frame_v2(encode_frame(GetCapabilities()), transaction)

    for fragment in fragments[:-1]:
        assert adapter.receive("EA3GNU", fragment.body, now=0) == "fragment"
    assert adapter.receive("EA3GNU", fragments[-1].body, now=0) == "completed"

    first_control = adapter.poll(now=0)
    assert any(
        parse_burst_control(packet.body) == ("ack", transaction, frozenset())
        for packet in first_control
    )

    # Simulate the APRS/WIDE duplicate seen in production: only the final
    # fragment reappears long after the transaction was already completed.
    assert adapter.receive("EA3GNU", fragments[-1].body, now=32) == "replayed"

    recovery = adapter.poll(now=32)
    assert any(
        parse_burst_control(packet.body) == ("ack", transaction, frozenset())
        for packet in recovery
    )

    # Crucially, the late 4/4 must not create fresh receive progress and poll()
    # must never emit N2 missing=1,2,3 every final_fragment_grace seconds.
    assert adapter.poll(now=34) == []
    assert adapter.poll(now=36) == []
    assert adapter.poll(now=60) == []
