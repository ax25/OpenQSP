"""M4.1 end-to-end private-message scenario."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from openqsp.protocol import Ack, AckStatus, End, Message, Operation


SCENARIO_PATH = (
    Path(__file__).parents[3] / "tools" / "scenarios" / "multi_user_private_message.py"
)
SPEC = spec_from_file_location("multi_user_private_message", SCENARIO_PATH)
assert SPEC and SPEC.loader
scenario = module_from_spec(SPEC)
sys.modules[SPEC.name] = scenario
SPEC.loader.exec_module(scenario)


def test_two_users_exchange_one_private_message_through_real_stack(tmp_path) -> None:
    result = scenario.run_scenario(tmp_path / "node.db")

    assert result.send == [Ack(scenario.MESSAGE_ID, AckStatus.STORED)]
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
    assert result.sender_mailbox == [
        End(Operation.GET_NEW_MESSAGES, 0, 0, False)
    ]
    assert result.third_user_mailbox == [
        End(Operation.GET_NEW_MESSAGES, 0, 0, False)
    ]
