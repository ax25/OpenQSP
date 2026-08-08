"""M4.2 end-to-end identical-message retry after a lost acknowledgement."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from openqsp.protocol import Ack, AckStatus, End, Message, Operation


SCENARIO_PATH = (
    Path(__file__).parents[3]
    / "tools"
    / "scenarios"
    / "message_retry_after_lost_ack.py"
)
SPEC = spec_from_file_location("message_retry_after_lost_ack", SCENARIO_PATH)
assert SPEC and SPEC.loader
scenario = module_from_spec(SPEC)
sys.modules[SPEC.name] = scenario
SPEC.loader.exec_module(scenario)


def test_identical_retry_after_lost_ack_is_idempotent(tmp_path) -> None:
    result = scenario.run_scenario(tmp_path / "node.db")

    assert result.first_send == [Ack(scenario.MESSAGE_ID, AckStatus.STORED)]
    assert result.retry_send == [
        Ack(scenario.MESSAGE_ID, AckStatus.ALREADY_STORED)
    ]
    assert result.first_send[0].object_id == result.retry_send[0].object_id

    assert result.recipient_mailbox == [
        Message(
            1,
            scenario.MESSAGE_ID,
            scenario.CREATED_AT,
            scenario.SENDER,
            scenario.RECIPIENT,
            scenario.BODY,
        ),
        End(Operation.GET_NEW_MESSAGES, 1, 1, False),
    ]

    # Reading again from the only returned sequence proves through the public
    # Core API that the retry neither created a copy nor consumed sequence 2.
    assert result.recipient_after_cursor == [
        End(Operation.GET_NEW_MESSAGES, 0, 1, False)
    ]
