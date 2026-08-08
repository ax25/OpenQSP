"""M4.1 end-to-end private-message scenario."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import inspect
import sys

from openqsp.protocol import Ack, AckStatus, End, Message, Operation


TOOLS_ROOT = Path(__file__).parents[3] / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from scenario_environment import LocalScenarioEnvironment  # noqa: E402

SCENARIO_PATH = (
    Path(__file__).parents[3] / "tools" / "scenarios" / "multi_user_private_message.py"
)
SPEC = spec_from_file_location("multi_user_private_message", SCENARIO_PATH)
assert SPEC and SPEC.loader
scenario = module_from_spec(SPEC)
sys.modules[SPEC.name] = scenario
SPEC.loader.exec_module(scenario)


def test_two_users_exchange_one_private_message_through_real_stack(tmp_path) -> None:
    result = scenario.run_scenario(LocalScenarioEnvironment(tmp_path / "node.db"))

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


def test_scenario_accepts_a_storage_free_fake_environment() -> None:
    """Prove the behavioral harness depends on clients, not local construction."""

    class FakeClient:
        def __init__(self, callsign: str) -> None:
            self.callsign = callsign

        def request(self, request):
            if self.callsign == scenario.SENDER and not isinstance(
                request, scenario.GetNewMessages
            ):
                return [Ack(scenario.MESSAGE_ID, AckStatus.STORED)]
            if self.callsign == scenario.RECIPIENT:
                return [
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
            return [End(Operation.GET_NEW_MESSAGES, 0, 0, False)]

    class FakeEnvironment:
        def client(self, callsign: str):
            return FakeClient(callsign)

    result = scenario.run_scenario(FakeEnvironment())

    assert result.send == [Ack(scenario.MESSAGE_ID, AckStatus.STORED)]
    assert result.recipient_mailbox[0].body == scenario.BODY
    assert list(inspect.signature(scenario.run_scenario).parameters) == ["env"]
