"""M4.5 end-to-end empty private-mailbox synchronization."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from openqsp.protocol import Stored, End, Message, Operation


TOOLS_ROOT = Path(__file__).parents[3] / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from scenario_environment import LocalScenarioEnvironment  # noqa: E402

SCENARIO_PATH = (
    Path(__file__).parents[3] / "tools" / "scenarios" / "empty_mailbox_sync.py"
)
SPEC = spec_from_file_location("empty_mailbox_sync", SCENARIO_PATH)
assert SPEC and SPEC.loader
scenario = module_from_spec(SPEC)
sys.modules[SPEC.name] = scenario
SPEC.loader.exec_module(scenario)


def test_empty_mailbox_sync_preserves_completed_cursor(tmp_path) -> None:
    result = scenario.run_scenario(LocalScenarioEnvironment(tmp_path / "node.db"))

    initial_end = End(Operation.GET_NEW_MESSAGES, 0, 0, False)
    assert result.initial_empty_sync == [initial_end]
    assert initial_end.request_operation == Operation.GET_NEW_MESSAGES
    assert initial_end.returned_count == 0
    assert initial_end.next_since == 0
    assert initial_end.has_more is False
    assert scenario.completed_cursor(
        result.initial_empty_sync, Operation.GET_NEW_MESSAGES
    ) == 0

    assert result.synced_send == [
        Stored()
    ]
    assert len(result.initial_sync) == 2
    assert isinstance(result.initial_sync[0], Message)
    assert result.initial_sync[0].sequence == 1
    assert isinstance(result.initial_sync[1], End)
    assert result.initial_sync[1].returned_count == 1
    assert result.cursor == scenario.completed_cursor(
        result.initial_sync, Operation.GET_NEW_MESSAGES
    )
    assert result.cursor == result.initial_sync[1].next_since

    assert result.other_send == [
        Stored()
    ]
    assert result.repeated_empty_sync == [
        End(Operation.GET_NEW_MESSAGES, 0, result.cursor, False)
    ]
    repeated_end = result.repeated_empty_sync[0]
    assert repeated_end.request_operation == Operation.GET_NEW_MESSAGES
    assert repeated_end.returned_count == 0
    assert repeated_end.next_since == result.cursor
    assert repeated_end.has_more is False
    assert not any(
        isinstance(response, Message) for response in result.repeated_empty_sync
    )
