"""M4.7 end-to-end node-restart persistence and synchronization recovery."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from openqsp.protocol import Ack, AckStatus, End, Message, Operation

SCENARIO_PATH = (
    Path(__file__).parents[3] / "tools" / "scenarios" / "node_restart_persistence.py"
)
SPEC = spec_from_file_location("node_restart_persistence", SCENARIO_PATH)
assert SPEC and SPEC.loader
scenario = module_from_spec(SPEC)
sys.modules[SPEC.name] = scenario
SPEC.loader.exec_module(scenario)

def _empty(cursor: int) -> list[End]:
    return [End(Operation.GET_NEW_MESSAGES, 0, cursor, False)]

def test_private_mailbox_sync_recovers_across_node_restart(tmp_path) -> None:
    result = scenario.run_scenario(tmp_path / "persistent-node.db")
    assert result.send_a == [Ack(scenario.MESSAGE_A.message_id, AckStatus.STORED)]
    assert len(result.first_sync) == 2
    message_a, first_end = result.first_sync
    assert message_a == Message(
        message_a.sequence,
        scenario.MESSAGE_A.message_id,
        scenario.MESSAGE_A.created_at,
        scenario.SENDER,
        scenario.RECIPIENT,
        scenario.MESSAGE_A.body,
    )
    assert isinstance(first_end, End)
    assert first_end == End(Operation.GET_NEW_MESSAGES, 1, message_a.sequence, False)
    # The scenario obtains this value only through completed_cursor(END).
    assert result.first_cursor == first_end.next_since
    assert result.unrelated_before_restart == _empty(0)

    # This since=0 retrieval occurs through a wholly reconstructed node.
    assert result.durable_sync == result.first_sync
    assert result.empty_from_old_cursor == _empty(result.first_cursor)
    assert result.send_b == [Ack(scenario.MESSAGE_B.message_id, AckStatus.STORED)]
    assert len(result.incremental_sync) == 2
    message_b, second_end = result.incremental_sync
    assert message_b == Message(
        message_b.sequence,
        scenario.MESSAGE_B.message_id,
        scenario.MESSAGE_B.created_at,
        scenario.SENDER,
        scenario.RECIPIENT,
        scenario.MESSAGE_B.body,
    )
    assert isinstance(second_end, End)
    assert second_end == End(Operation.GET_NEW_MESSAGES, 1, message_b.sequence, False)
    assert message_b.message_id != message_a.message_id
    assert message_b.sequence > message_a.sequence
    assert second_end.next_since > result.first_cursor
    assert len({message_a.message_id, message_b.message_id}) == 2
    assert len({message_a.sequence, message_b.sequence}) == 2
    assert scenario.MESSAGE_A.message_id not in {
        item.message_id for item in result.incremental_sync if isinstance(item, Message)
    }
    assert result.unrelated_after_restart == _empty(0)
    assert result.sender_after_restart == _empty(0)
