#!/usr/bin/env python3
"""Deterministic APRS simulator built from the production profile machinery."""

from __future__ import annotations

import argparse
import random
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from openqsp.protocol import GetCapabilities, SendMessage, encode_frame
from openqsp.server import ServerCore
from openqsp.storage import BulletinStore, Database, MessageStore
from openqsp.transport.aprs import AdapterConfig, APRSAdapter
from openqsp.transport.aprs.carriage import APRSFragment, fragment_frame, parse_fragment
from openqsp.transport.aprs.state import Reassembler


@dataclass
class Faults:
    """Fault selectors are fragment indexes and affect the first attempt."""

    drop_packets: set[int] = field(default_factory=set)
    drop_packets_always: set[int] = field(default_factory=set)
    duplicate_packets: set[int] = field(default_factory=set)
    delay_packets: dict[int, float] = field(default_factory=dict)
    reorder: bool = False
    drop_acks: set[int] = field(default_factory=set)
    duplicate_acks: set[int] = field(default_factory=set)
    drop_response_acks: set[int] = field(default_factory=set)
    stale_ack: str | None = None


class VirtualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class _ClientFragment:
    fragment: APRSFragment
    attempts: int = 0
    acked: bool = False
    deadline: float = 0.0


class APRSSimulator:
    """Two-way virtual-time reliability harness around the real service adapter."""

    def __init__(
        self,
        core: ServerCore,
        *,
        seed: int = 0,
        faults: Faults | None = None,
        ack_timeout: float = 1.0,
        max_attempts: int = 3,
    ) -> None:
        self.random = random.Random(seed)
        self.faults = faults or Faults()
        self.clock = VirtualClock()
        self.ack_timeout = ack_timeout
        self.max_attempts = max_attempts
        self.adapter = APRSAdapter(
            core,
            config=AdapterConfig(
                ack_timeout=ack_timeout,
                max_attempts=max_attempts,
                min_interval=0,
            ),
            clock=self.clock,
        )
        self.transcript: list[str] = []
        self.client_failures: list[str] = []
        self.dispositions: list[str] = []

    def request(
        self, peer: str, frame: bytes, transaction_id: str = "000"
    ) -> list[bytes]:
        """Reliably carry one client transaction and all service responses."""
        states = []
        for number, fragment in enumerate(fragment_frame(frame, transaction_id)):
            message_id = f"{number:02X}"
            states.append(
                _ClientFragment(
                    APRSFragment(
                        fragment.transaction_id,
                        fragment.index,
                        fragment.total,
                        fragment.data,
                        message_id,
                    )
                )
            )
        response_reassembly = Reassembler(ttl=30, max_entries=32)
        responses: list[bytes] = []
        if self.faults.stale_ack:
            disposition = self.adapter.receive(
                peer, f"ack{self.faults.stale_ack}", now=self.clock()
            )
            self.transcript.append(f"STALE ack{self.faults.stale_ack} [{disposition}]")

        for _ in range(512):
            due = [
                state
                for state in states
                if not state.acked
                and state.attempts < self.max_attempts
                and self.clock() >= state.deadline
            ]
            if self.faults.reorder and any(state.attempts == 0 for state in due):
                self.random.shuffle(due)
            for state in due:
                state.attempts += 1
                state.deadline = self.clock() + self.ack_timeout
                index = state.fragment.index
                body = state.fragment.body
                drop = index in self.faults.drop_packets_always or (
                    state.attempts == 1 and index in self.faults.drop_packets
                )
                if drop:
                    self.transcript.append(f"DROP#{state.attempts} {peer}>OPENQSP {body}")
                    continue
                if state.attempts == 1 and index in self.faults.delay_packets:
                    self.clock.advance(self.faults.delay_packets[index])
                copies = (
                    2
                    if state.attempts == 1 and index in self.faults.duplicate_packets
                    else 1
                )
                for _copy in range(copies):
                    disposition = self.adapter.receive(peer, body, now=self.clock())
                    self.dispositions.append(disposition)
                    self.transcript.append(
                        f"RX#{state.attempts} {peer}>OPENQSP {body} [{disposition}]"
                    )

            packets = self.adapter.poll(now=self.clock())
            for packet in packets:
                self.transcript.append(
                    f"TX {packet.source}>{packet.destination} {packet.body}"
                )
                if packet.is_ack:
                    message_id = packet.body.removeprefix("ack")
                    state = next(
                        (
                            item
                            for item in states
                            if item.fragment.message_id == message_id
                        ),
                        None,
                    )
                    if state is None:
                        continue
                    index = state.fragment.index
                    if state.attempts == 1 and index in self.faults.drop_acks:
                        self.transcript.append(f"DROP ACK {packet.body}")
                        continue
                    state.acked = True
                    self.transcript.append(f"CLIENT ACKED {packet.body}")
                    if index in self.faults.duplicate_acks:
                        self.transcript.append(f"DUPLICATE ACK {packet.body}")
                    continue

                fragment = parse_fragment(packet.body)
                result = response_reassembly.add("OPENQSP", fragment, self.clock())
                if fragment.index not in self.faults.drop_response_acks:
                    self.adapter.receive(
                        peer, f"ack{fragment.message_id}", now=self.clock()
                    )
                    self.transcript.append(
                        f"ACK {peer}>OPENQSP ack{fragment.message_id}"
                    )
                if result is not None:
                    responses.append(result)

            exhausted = [
                state
                for state in states
                if not state.acked
                and state.attempts >= self.max_attempts
                and self.clock() >= state.deadline
            ]
            for state in exhausted:
                label = f"{peer}:{state.fragment.message_id}"
                if label not in self.client_failures:
                    self.client_failures.append(label)

            client_done = all(state.acked or state in exhausted for state in states)
            server_done = (
                self.adapter.queued_count == 0 and self.adapter.pending_count == 0
            )
            if client_done and server_done:
                break
            self.clock.advance(self.ack_timeout)
        else:
            raise RuntimeError("simulator event bound exhausted")
        return responses


class _CountingCore(ServerCore):
    def __init__(self, *, message_store: MessageStore, bulletin_store: BulletinStore):
        super().__init__(message_store=message_store, bulletin_store=bulletin_store)
        self.calls = 0

    def handle_frame(self, authenticated_callsign: str, frame_bytes: bytes) -> list[bytes]:
        self.calls += 1
        return super().handle_frame(authenticated_callsign, frame_bytes)


def conformance() -> tuple[bool, list[str]]:
    """Run the normative local workflows and return their combined transcript."""
    transcript: list[str] = []
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "openqsp.sqlite")
        database.initialize()

        def simulator(faults: Faults | None = None) -> tuple[_CountingCore, APRSSimulator]:
            core = _CountingCore(
                message_store=MessageStore(database),
                bulletin_store=BulletinStore(database),
            )
            return core, APRSSimulator(core, seed=7, faults=faults)

        small = encode_frame(GetCapabilities())
        large = encode_frame(SendMessage(1, "EA3BBB", "x" * 208))

        # A: canonical multi-fragment round trip.
        fragments = fragment_frame(large, "0A0")
        reassembler = Reassembler()
        recovered = None
        for fragment in reversed(fragments):
            recovered = reassembler.add("EA3AAA", fragment, 0) or recovered
        checks = [recovered == large]

        # B: initial fragment loss is retried client -> service.
        core, sim = simulator(Faults(drop_packets={0}))
        checks.append(bool(sim.request("EA3AAA", large, "0A1")) and core.calls == 1)
        checks.append(any(line.startswith("RX#2") for line in sim.transcript))
        transcript.extend(sim.transcript)

        # C: lost inbound ACK causes same-ID retransmit, but only one Core call.
        core, sim = simulator(Faults(drop_acks={0}))
        checks.append(bool(sim.request("EA3AAA", small, "0A2")) and core.calls == 1)
        checks.append(any(line.startswith("RX#2") and "{00" in line for line in sim.transcript))
        transcript.extend(sim.transcript)

        # D: reordering and exact duplicate fragments complete once.
        core, sim = simulator(Faults(reorder=True, duplicate_packets={0}))
        checks.append(bool(sim.request("EA3AAA", large, "0A3")) and core.calls == 1)
        transcript.extend(sim.transcript)

        # E/F: completed replay is cached; changed bytes conflict.
        core, sim = simulator()
        first = sim.request("EA3AAA", small, "0A4")
        replayed = sim.request("EA3AAA", small, "0A4")
        before_conflict = core.calls
        sim.request("EA3AAA", encode_frame(SendMessage(1, "EA3BBB", "different")), "0A4")
        checks.extend(
            [first == replayed, core.calls == before_conflict == 1, "conflict" in sim.dispositions]
        )
        transcript.extend(sim.transcript)

        # G: a stale ACK is ignored.
        core, sim = simulator(Faults(stale_ack="ZZ"))
        checks.append(bool(sim.request("EA3AAA", small, "0A5")))
        checks.append(any("STALE ackZZ [ignored]" in line for line in sim.transcript))
        transcript.extend(sim.transcript)

        # H: permanent client-side loss exhausts bounded attempts.
        core, sim = simulator(Faults(drop_packets_always={0}))
        checks.append(not sim.request("EA3AAA", small, "0A6"))
        checks.extend([core.calls == 0, len(sim.client_failures) == 1])
        transcript.extend(sim.transcript)

    return all(checks), transcript


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conformance", action="store_true")
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
