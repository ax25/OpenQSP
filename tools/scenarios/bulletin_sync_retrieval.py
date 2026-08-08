#!/usr/bin/env python3
"""Run the M4.8 public bulletin synchronization and retrieval scenario."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from client_sim import completed_cursor  # noqa: E402
from scenario_environment import (  # noqa: E402
    LocalScenarioEnvironment,
    ScenarioEnvironment,
)
from openqsp.protocol import (  # noqa: E402
    Bulletin,
    BulletinHeader,
    End,
    Error,
    GetBulletin,
    GetNewBulletins,
    Operation,
    ProtocolObject,
)


CLIENT = "EA3AAA"
SOURCE = "EA9SRC"
SYNC_LIMIT = 20

BULLETIN_A = Bulletin(
    1, 1_786_800_001, SOURCE, "M4.8 bulletin A", "Complete body A"
)
BULLETIN_B = Bulletin(
    2, 1_786_800_002, SOURCE, "M4.8 bulletin B", "Complete body B"
)
BULLETIN_C = Bulletin(
    3, 1_786_800_003, SOURCE, "M4.8 bulletin C", "Complete body C"
)
MISSING_BULLETIN_ID = 0x4D48FFFF


@dataclass(frozen=True)
class ScenarioResult:
    """Decoded public-stack responses and END-derived synchronization cursors."""

    initial_sync: list[ProtocolObject]
    initial_cursor: int
    retrieved: list[ProtocolObject]
    incremental_sync: list[ProtocolObject]
    incremental_cursor: int
    empty_sync: list[ProtocolObject]
    missing: list[ProtocolObject]


def _cursor(responses: list[ProtocolObject]) -> int:
    cursor = completed_cursor(responses, Operation.GET_NEW_BULLETINS)
    if cursor is None:
        raise AssertionError("bulletin synchronization did not end with a valid END")
    return cursor


def run_scenario(env: ScenarioEnvironment) -> ScenarioResult:
    """Run all M4.8 phases through the persistent production Core stack."""
    client = env.client(CLIENT)

    env.seed_bulletin(BULLETIN_A)
    env.seed_bulletin(BULLETIN_B)
    initial_sync = client.request(GetNewBulletins(0, SYNC_LIMIT))
    initial_cursor = _cursor(initial_sync)

    headers = [item for item in initial_sync if isinstance(item, BulletinHeader)]
    if len(headers) != 2:
        raise AssertionError(f"expected two initial headers, got {initial_sync!r}")
    # Retrieval deliberately follows the identifier supplied by synchronization.
    retrieved = client.request(GetBulletin(headers[0].sequence))

    env.seed_bulletin(BULLETIN_C)
    incremental_sync = client.request(GetNewBulletins(initial_cursor, SYNC_LIMIT))
    incremental_cursor = _cursor(incremental_sync)
    empty_sync = client.request(GetNewBulletins(incremental_cursor, SYNC_LIMIT))
    missing = client.request(GetBulletin(MISSING_BULLETIN_ID))

    return ScenarioResult(
        initial_sync,
        initial_cursor,
        retrieved,
        incremental_sync,
        incremental_cursor,
        empty_sync,
        missing,
    )


def _print_sync(since: int, responses: list[ProtocolObject]) -> None:
    print(f"{CLIENT} -> GET_NEW_BULLETINS since={since}")
    for response in responses:
        if isinstance(response, BulletinHeader):
            print(f"HEADER {response.title} id={response.sequence}")
        elif isinstance(response, End):
            more = str(response.has_more).lower()
            print(
                f"END returned={response.returned_count} "
                f"next_since={response.next_since} has_more={more}"
            )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: bulletin_sync_retrieval.py DATABASE", file=sys.stderr)
        return 2

    result = run_scenario(LocalScenarioEnvironment(argv[0]))
    print("Seeded bulletin A")
    print("Seeded bulletin B\n")
    _print_sync(0, result.initial_sync)
    print(f"\nCompleted bulletin cursor: {result.initial_cursor}\n")

    bulletin = result.retrieved[0]
    assert isinstance(bulletin, Bulletin)
    print(f"{CLIENT} -> GET_BULLETIN {bulletin.sequence}")
    print(f"BULLETIN {bulletin.sequence}")
    print(f"title: {bulletin.title}")
    print(f"body: {bulletin.body}\n")

    print("Seeded bulletin C\n")
    _print_sync(result.initial_cursor, result.incremental_sync)
    print()
    _print_sync(result.incremental_cursor, result.empty_sync)
    print(f"\nGET_BULLETIN {MISSING_BULLETIN_ID}")
    error = result.missing[0]
    assert isinstance(error, Error)
    print(f"ERROR {error.error_code.name}\n")
    print("M4.8 bulletin synchronization scenario: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
