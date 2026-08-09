from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from openqsp.protocol import GetCapabilities, SendMessage, encode_frame
from openqsp.server import ServerCore

SPEC = spec_from_file_location(
    "aprs_sim", Path(__file__).parents[3] / "tools" / "aprs_sim.py"
)
assert SPEC and SPEC.loader
aprs_sim = module_from_spec(SPEC)
sys.modules[SPEC.name] = aprs_sim
SPEC.loader.exec_module(aprs_sim)
APRSSimulator = aprs_sim.APRSSimulator
Faults = aprs_sim.Faults
conformance = aprs_sim.conformance


class CountingCore(ServerCore):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def handle_frame(
        self, authenticated_callsign: str, frame_bytes: bytes
    ) -> list[bytes]:
        self.calls += 1
        return super().handle_frame(authenticated_callsign, frame_bytes)


def test_complete_m7_simulator_conformance_asserts_all_workflows() -> None:
    passed, transcript = conformance()
    assert passed
    assert any(line.startswith("DROP#1") for line in transcript)
    assert any(line.startswith("RX#2") for line in transcript)
    assert any("DROP ACK" in line for line in transcript)
    assert any("[replayed]" in line for line in transcript)
    assert any("[conflict]" in line for line in transcript)


def test_client_fragment_loss_retries_same_id_and_invokes_core_once() -> None:
    core = CountingCore()
    simulator = APRSSimulator(core, faults=Faults(drop_packets={0}))
    large = encode_frame(SendMessage(1, "EA3BBB", "x" * 208))
    assert simulator.request("EA3AAA", large, "100")
    assert core.calls == 1
    attempts = [
        line for line in simulator.transcript if "EA3AAA>OPENQSP" in line and "{00" in line
    ]
    assert attempts[0].startswith("DROP#1")
    assert attempts[1].startswith("RX#2")


def test_lost_ack_retries_same_fragment_id_without_duplicate_core_effect() -> None:
    core = CountingCore()
    simulator = APRSSimulator(core, faults=Faults(drop_acks={0}))
    assert simulator.request("EA3AAA", encode_frame(GetCapabilities()), "101")
    assert core.calls == 1
    deliveries = [
        line for line in simulator.transcript if line.startswith("RX#") and "{00" in line
    ]
    assert deliveries[0].startswith("RX#1")
    assert deliveries[1].startswith("RX#2")


def test_client_retry_exhaustion_is_bounded_and_releases_transaction() -> None:
    core = CountingCore()
    simulator = APRSSimulator(
        core,
        faults=Faults(drop_packets_always={0}),
        max_attempts=2,
    )
    assert simulator.request("EA3AAA", encode_frame(GetCapabilities()), "102") == []
    assert core.calls == 0
    assert simulator.client_failures == ["EA3AAA:00"]
    assert len([line for line in simulator.transcript if line.startswith("DROP#")]) == 2


def test_delay_duplicate_and_reorder_faults_are_deterministic() -> None:
    core = CountingCore()
    simulator = APRSSimulator(
        core,
        seed=42,
        faults=Faults(
            delay_packets={0: 0.5},
            duplicate_packets={0},
            duplicate_acks={0},
            reorder=True,
        ),
    )
    large = encode_frame(SendMessage(1, "EA3BBB", "x" * 208))
    assert simulator.request("EA3AAA", large, "103")
    assert simulator.clock() >= 0.5
    assert core.calls == 1
    assert any("DUPLICATE ACK ack00" in line for line in simulator.transcript)
