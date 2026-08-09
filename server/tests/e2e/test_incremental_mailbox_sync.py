"""M4.4 end-to-end incremental private-mailbox synchronization."""

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from openqsp.protocol import End, Message, Operation, Stored

TOOLS_ROOT = Path(__file__).parents[3] / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from scenario_environment import LocalScenarioEnvironment

SCENARIO_PATH = (
    Path(__file__).parents[3] / "tools" / "scenarios" / "incremental_mailbox_sync.py"
)
SPEC = spec_from_file_location("incremental_mailbox_sync", SCENARIO_PATH)
assert SPEC and SPEC.loader
scenario = module_from_spec(SPEC)
sys.modules[SPEC.name] = scenario
SPEC.loader.exec_module(scenario)


def _stored_response() -> list[Stored]:
    return [Stored()]


def test_mailbox_sync_reuses_end_cursors_without_duplicates(tmp_path) -> None:
    result = scenario.run_scenario(LocalScenarioEnvironment(tmp_path / "node.db"))

    assert result.initial_sends == [
        _stored_response(),
        _stored_response(),
        _stored_response(),
    ]
    assert result.first_sync == [
        Message(1, scenario.MESSAGE_A.created_at,
                "EA3AAA", scenario.RECIPIENT, scenario.MESSAGE_A.body),
        Message(2, scenario.MESSAGE_B.created_at,
                "EA3CCC", scenario.RECIPIENT, scenario.MESSAGE_B.body),
        End(Operation.GET_NEW_MESSAGES, 2, 2, False),
    ]
    first_messages = result.first_sync[:-1]
    first_end = result.first_sync[-1]
    assert [message.sequence for message in first_messages] == [1, 2]
    assert all(message.recipient == scenario.RECIPIENT for message in first_messages)
    assert first_end.returned_count == len(first_messages) == 2
    assert first_end.next_since == first_messages[-1].sequence
    assert first_end.has_more is False
    assert result.first_cursor == first_end.next_since

    assert result.later_sends == [
        _stored_response(),
        _stored_response(),
    ]
    assert result.second_sync == [
        Message(3, scenario.MESSAGE_C.created_at,
                "EA3AAA", scenario.RECIPIENT, scenario.MESSAGE_C.body),
        Message(4, scenario.MESSAGE_D.created_at,
                "EA3DDD", scenario.RECIPIENT, scenario.MESSAGE_D.body),
        End(Operation.GET_NEW_MESSAGES, 2, 4, False),
    ]
    second_messages = result.second_sync[:-1]
    second_end = result.second_sync[-1]
    assert [message.sequence for message in second_messages] == [3, 4]
    assert not {message.sequence for message in first_messages} & {
        message.sequence for message in second_messages
    }
    assert all(
        message.sequence > first_end.next_since for message in second_messages
    )
    assert [message.sequence for message in second_messages] == sorted(
        message.sequence for message in second_messages
    )
    assert second_end.returned_count == len(second_messages) == 2
    assert second_end.next_since == second_messages[-1].sequence
    assert second_end.has_more is False
    assert result.second_cursor == second_end.next_since
    assert result.second_cursor > result.first_cursor

    assert result.third_sync == [
        End(Operation.GET_NEW_MESSAGES, 0, result.second_cursor, False)
    ]
    empty_end = result.third_sync[0]
    assert empty_end.returned_count == 0
    assert empty_end.next_since == result.second_cursor
    assert empty_end.has_more is False
