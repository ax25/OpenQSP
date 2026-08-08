"""M4.8 end-to-end public bulletin synchronization and retrieval."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from openqsp.protocol import Bulletin, BulletinHeader, End, Error, ErrorCode, Operation

TOOLS_ROOT = Path(__file__).parents[3] / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))
from scenario_environment import LocalScenarioEnvironment

SCENARIO_PATH = (
    Path(__file__).parents[3] / "tools" / "scenarios" / "bulletin_sync_retrieval.py"
)
SPEC = spec_from_file_location("bulletin_sync_retrieval", SCENARIO_PATH)
assert SPEC and SPEC.loader
scenario = module_from_spec(SPEC)
sys.modules[SPEC.name] = scenario
SPEC.loader.exec_module(scenario)


def _header(sequence: int, bulletin: Bulletin) -> BulletinHeader:
    return BulletinHeader(
        sequence, bulletin.created_at, bulletin.author, bulletin.title
    )


def test_bulletin_sync_retrieval_and_resume(tmp_path) -> None:
    result = scenario.run_scenario(LocalScenarioEnvironment(tmp_path / "node.db"))
    first_headers = result.initial_sync[:-1]
    first_end = result.initial_sync[-1]
    assert first_headers == [
        _header(1, scenario.BULLETIN_A),
        _header(2, scenario.BULLETIN_B),
    ]
    assert [header.sequence for header in first_headers] == [1, 2]
    assert all((isinstance(header, BulletinHeader) for header in first_headers))
    assert not any((hasattr(header, "body") for header in first_headers))
    assert first_end == End(
        Operation.GET_NEW_BULLETINS, 2, result.initial_cursor, False
    )
    assert result.initial_cursor == scenario.completed_cursor(
        result.initial_sync, Operation.GET_NEW_BULLETINS
    )
    synchronized_id = first_headers[0].sequence
    assert result.retrieved == [
        Bulletin(
            1,
            scenario.BULLETIN_A.created_at,
            scenario.BULLETIN_A.author,
            scenario.BULLETIN_A.title,
            scenario.BULLETIN_A.body,
        )
    ]
    retrieved = result.retrieved[0]
    assert retrieved.sequence == synchronized_id
    assert (retrieved.created_at, retrieved.title, retrieved.body) == (
        scenario.BULLETIN_A.created_at,
        scenario.BULLETIN_A.title,
        scenario.BULLETIN_A.body,
    )
    assert not hasattr(retrieved, "recipient")
    later_headers = result.incremental_sync[:-1]
    later_end = result.incremental_sync[-1]
    assert later_headers == [_header(3, scenario.BULLETIN_C)]
    assert len({header.sequence for header in later_headers}) == 1
    assert not {scenario.BULLETIN_A.sequence, scenario.BULLETIN_B.sequence} & {
        header.sequence for header in later_headers
    }
    assert later_end == End(
        Operation.GET_NEW_BULLETINS, 1, result.incremental_cursor, False
    )
    assert result.incremental_cursor == scenario.completed_cursor(
        result.incremental_sync, Operation.GET_NEW_BULLETINS
    )
    assert result.incremental_cursor > result.initial_cursor
    assert result.empty_sync == [
        End(Operation.GET_NEW_BULLETINS, 0, result.incremental_cursor, False)
    ]
    assert (
        scenario.completed_cursor(result.empty_sync, Operation.GET_NEW_BULLETINS)
        == result.incremental_cursor
    )
    assert result.missing == [
        Error(Operation.GET_BULLETIN, ErrorCode.NOT_FOUND, "bulletin not found")
    ]
