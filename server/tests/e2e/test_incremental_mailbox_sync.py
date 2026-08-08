"""End-to-end incremental mailbox synchronization."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from openqsp.protocol import End, Message, Operation, Stored

ROOT = Path(__file__).parents[3] / "tools"
sys.path.insert(0, str(ROOT)) if str(ROOT) not in sys.path else None
from scenario_environment import LocalScenarioEnvironment

spec = spec_from_file_location(
    "incremental_mailbox_sync", ROOT / "scenarios/incremental_mailbox_sync.py"
)
scenario = module_from_spec(spec)
sys.modules[spec.name] = scenario
spec.loader.exec_module(scenario)


def test_mailbox_sync_reuses_end_cursors_without_duplicates(tmp_path):
    r = scenario.run_scenario(LocalScenarioEnvironment(tmp_path / "x.db"))
    assert r.initial_sends == [[Stored()]] * 3
    first = r.first_sync[:-1]
    assert [x.sequence for x in first] == [1, 2]
    assert [x.body for x in first] == [scenario.MESSAGE_A.body, scenario.MESSAGE_B.body]
    assert r.first_sync[-1] == End(Operation.GET_NEW_MESSAGES, 2, 2, False)
    second = r.second_sync[:-1]
    assert [x.sequence for x in second] == [3, 4]
    assert r.second_sync[-1].next_since == 4
    assert r.third_sync == [End(Operation.GET_NEW_MESSAGES, 0, 4, False)]
