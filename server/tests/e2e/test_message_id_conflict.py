"""M4.3 end-to-end conflicting reuse of a message identifier."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from openqsp.protocol import Ack, AckStatus, End, Message, Operation


SCENARIO_PATH = (
    Path(__file__).parents[3] / "tools" / "scenarios" / "message_id_conflict.py"
)
SPEC = spec_from_file_location("message_id_conflict", SCENARIO_PATH)
assert SPEC and SPEC.loader
scenario = module_from_spec(SPEC)
sys.modules[SPEC.name] = scenario
SPEC.loader.exec_module(scenario)


def test_changed_body_with_stored_message_id_is_rejected(tmp_path) -> None:
    result = scenario.run_scenario(tmp_path / "node.db")

    assert result.original_send == [
        Ack(scenario.MESSAGE_ID, AckStatus.STORED)
    ]
    assert result.conflicting_send == [
        Ack(scenario.MESSAGE_ID, AckStatus.CONFLICT)
    ]
    assert result.original_send[0].object_id == result.conflicting_send[0].object_id
    assert scenario.ORIGINAL_BODY != scenario.CONFLICTING_BODY

    assert result.recipient_mailbox == [
        Message(
            1,
            scenario.MESSAGE_ID,
            scenario.CREATED_AT,
            scenario.SENDER,
            scenario.RECIPIENT,
            scenario.ORIGINAL_BODY,
        ),
        End(Operation.GET_NEW_MESSAGES, 1, 1, False),
    ]
    message, end = result.recipient_mailbox
    assert message.message_id == scenario.MESSAGE_ID
    assert message.author == scenario.SENDER
    assert message.recipient == scenario.RECIPIENT
    assert message.body == scenario.ORIGINAL_BODY
    assert scenario.CONFLICTING_BODY not in message.body
    assert message.sequence == 1
    assert end.returned_count == 1
    assert end.next_since == message.sequence
    assert end.has_more is False

    # No object after sequence 1 means no duplicate and no consumed sequence 2.
    assert result.recipient_after_cursor == [
        End(Operation.GET_NEW_MESSAGES, 0, 1, False)
    ]
