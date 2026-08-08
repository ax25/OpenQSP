"""M4.6 end-to-end private-mailbox pagination and has_more scenario."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from openqsp.protocol import Ack, AckStatus, End, Message, Operation


TOOLS_ROOT = Path(__file__).parents[3] / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from scenario_environment import LocalScenarioEnvironment  # noqa: E402

SCENARIO_PATH = (
    Path(__file__).parents[3] / "tools" / "scenarios" / "mailbox_pagination.py"
)
SPEC = spec_from_file_location("mailbox_pagination", SCENARIO_PATH)
assert SPEC and SPEC.loader
scenario = module_from_spec(SPEC)
sys.modules[SPEC.name] = scenario
SPEC.loader.exec_module(scenario)


def _messages(page: list[object]) -> list[Message]:
    return [response for response in page if isinstance(response, Message)]


def _end(page: list[object]) -> End:
    assert isinstance(page[-1], End)
    return page[-1]


def test_mailbox_paginates_with_end_cursors_and_interleaved_sequences(tmp_path) -> None:
    result = scenario.run_scenario(LocalScenarioEnvironment(tmp_path / "node.db"))

    assert result.sends == [
        [Ack(message.message_id, AckStatus.STORED)]
        for _, message in scenario.SUBMISSIONS
    ]
    assert len(result.pages) == 4

    first, second, final, empty = result.pages
    first_messages = _messages(first)
    second_messages = _messages(second)
    final_messages = _messages(final)
    first_end, second_end, final_end, empty_end = map(
        _end, (first, second, final, empty)
    )

    assert len(first) == scenario.PAGE_SIZE + 1
    assert [message.message_id for message in first_messages] == [
        scenario.MESSAGE_A.message_id,
        scenario.MESSAGE_B.message_id,
    ]
    assert [message.sequence for message in first_messages] == [1, 3]
    assert first_end.returned_count == len(first_messages) == scenario.PAGE_SIZE
    assert first_end.next_since == first_messages[-1].sequence
    assert first_end.has_more is True
    assert result.request_since[1] == scenario.completed_cursor(
        first, Operation.GET_NEW_MESSAGES
    )

    assert len(second) == scenario.PAGE_SIZE + 1
    assert result.request_since[1] == first_end.next_since
    assert [message.message_id for message in second_messages] == [
        scenario.MESSAGE_C.message_id,
        scenario.MESSAGE_D.message_id,
    ]
    assert not {message.message_id for message in first_messages} & {
        message.message_id for message in second_messages
    }
    assert second_end.returned_count == len(second_messages) == scenario.PAGE_SIZE
    assert second_end.next_since == second_messages[-1].sequence
    assert second_end.next_since > first_end.next_since
    assert second_end.has_more is True
    assert result.request_since[2] == scenario.completed_cursor(
        second, Operation.GET_NEW_MESSAGES
    )

    assert len(final) == 2
    assert result.request_since[2] == second_end.next_since
    assert [message.message_id for message in final_messages] == [
        scenario.MESSAGE_E.message_id
    ]
    assert final_end.returned_count == len(final_messages) == 1
    assert final_end.next_since == final_messages[-1].sequence
    assert final_end.has_more is False
    assert result.request_since[3] == scenario.completed_cursor(
        final, Operation.GET_NEW_MESSAGES
    )

    assert result.request_since[3] == final_end.next_since
    assert empty == [
        End(Operation.GET_NEW_MESSAGES, 0, final_end.next_since, False)
    ]
    assert empty_end.returned_count == 0
    assert empty_end.next_since == final_end.next_since
    assert empty_end.has_more is False

    received = first_messages + second_messages + final_messages
    received_ids = [message.message_id for message in received]
    expected_ids = [message.message_id for message in scenario.MAILBOX_MESSAGES]
    assert received_ids == expected_ids
    assert len(received_ids) == len(set(received_ids))
    assert [message.sequence for message in received] == sorted(
        message.sequence for message in received
    )
    assert all(message.recipient == scenario.RECIPIENT for message in received)
    assert not {
        scenario.OTHER_MESSAGE_X.message_id,
        scenario.OTHER_MESSAGE_Y.message_id,
    } & set(received_ids)
