#!/usr/bin/env python3
"""Deterministic APRS profile simulator using the production adapter.

Run ``PYTHONPATH=server/src python tools/aprs_sim.py --conformance`` for a
local Core request/response exchange.  No network, radio, or real-time sleeps
are used.
"""

from __future__ import annotations

import argparse
import random
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from openqsp.protocol import GetCapabilities, decode_frame, encode_frame
from openqsp.server import ServerCore
from openqsp.storage import BulletinStore, Database, MessageStore
from openqsp.transport.aprs import APRSAdapter, AdapterConfig
from openqsp.transport.aprs.carriage import fragment_frame, parse_fragment
from openqsp.transport.aprs.state import Reassembler


@dataclass
class Faults:
    drop_packets: set[int] = field(default_factory=set)
    duplicate_packets: set[int] = field(default_factory=set)
    delay_packets: dict[int, float] = field(default_factory=dict)
    reorder: bool = False
    drop_acks: set[int] = field(default_factory=set)
    duplicate_acks: set[int] = field(default_factory=set)
    stale_ack: str | None = None


class VirtualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class APRSSimulator:
    """Observable seeded fault harness around a production service adapter."""

    def __init__(self, core: ServerCore, *, seed: int = 0, faults: Faults | None = None) -> None:
        self.random = random.Random(seed)
        self.faults = faults or Faults()
        self.clock = VirtualClock()
        self.adapter = APRSAdapter(core, config=AdapterConfig(
            ack_timeout=1, max_attempts=3, min_interval=0,
        ), clock=self.clock)
        self.transcript: list[str] = []

    def request(self, peer: str, frame: bytes, transaction_id: str = "000") -> list[bytes]:
        fragments = list(fragment_frame(frame, transaction_id))
        if self.faults.reorder:
            self.random.shuffle(fragments)
        deliveries: list[tuple[float, int, object]] = []
        for number, fragment in enumerate(fragments):
            message_id = f"{number:02X}"
            body = type(fragment)(fragment.transaction_id, fragment.index,
                                  fragment.total, fragment.data, message_id).body
            if number in self.faults.drop_packets:
                self.transcript.append(f"DROP {peer}>OPENQSP {body}")
                continue
            count = 2 if number in self.faults.duplicate_packets else 1
            deliveries.extend((self.faults.delay_packets.get(number, 0), number, body) for _ in range(count))
        for delay, _, body in sorted(deliveries, key=lambda value: value[0]):
            self.clock.advance(delay)
            disposition = self.adapter.receive(peer, str(body), now=self.clock())
            self.transcript.append(f"RX {peer}>OPENQSP {body} [{disposition}]")
        response_reassembly = Reassembler(ttl=30, max_entries=32)
        responses: list[bytes] = []
        if self.faults.stale_ack:
            self.adapter.receive(peer, f"ack{self.faults.stale_ack}")
        for step in range(256):
            packets = self.adapter.poll(now=self.clock())
            for packet in packets:
                self.transcript.append(f"TX {packet.source}>{packet.destination} {packet.body}")
                if packet.is_ack:
                    continue
                fragment = parse_fragment(packet.body)
                result = response_reassembly.add("OPENQSP", fragment, self.clock())
                ack_number = len([line for line in self.transcript if line.startswith("ACK ")])
                if ack_number not in self.faults.drop_acks:
                    self.adapter.receive(peer, f"ack{fragment.message_id}", now=self.clock())
                    self.transcript.append(f"ACK {peer}>OPENQSP ack{fragment.message_id}")
                    if ack_number in self.faults.duplicate_acks:
                        self.adapter.receive(peer, f"ack{fragment.message_id}", now=self.clock())
                if result is not None:
                    responses.append(result)
            if self.adapter.queued_count == 0 and self.adapter.pending_count == 0:
                break
            self.clock.advance(1)
        return responses


def conformance() -> tuple[bool, list[str]]:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "openqsp.sqlite")
        database.initialize()
        core = ServerCore(message_store=MessageStore(database), bulletin_store=BulletinStore(database))
        simulator = APRSSimulator(core, seed=7, faults=Faults(reorder=True, duplicate_packets={0}))
        request = encode_frame(GetCapabilities())
        responses = simulator.request("EA3AAA-10", request, "0A7")
        valid = bool(responses) and all(
            decode_frame(response).protocol_version == 1  # type: ignore[union-attr]
            for response in responses
        )
        return valid, simulator.transcript


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conformance", action="store_true", help="run the local Core workflow")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    if not args.conformance:
        parser.error("select --conformance")
    valid, transcript = conformance()
    if not args.quiet:
        print("\n".join(transcript))
        print("M7 APRS simulator conformance: " + ("PASS" if valid else "FAIL"))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
