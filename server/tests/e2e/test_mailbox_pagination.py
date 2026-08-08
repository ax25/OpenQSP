from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from openqsp.protocol import End, Message, Stored

ROOT = Path(__file__).parents[3] / "tools"
sys.path.insert(0, str(ROOT)) if str(ROOT) not in sys.path else None
from scenario_environment import LocalScenarioEnvironment

spec = spec_from_file_location(
    "mailbox_pagination", ROOT / "scenarios/mailbox_pagination.py"
)
scenario = module_from_spec(spec)
sys.modules[spec.name] = scenario
spec.loader.exec_module(scenario)


def test_mailbox_paginates_with_end_cursors_and_interleaved_sequences(tmp_path):
    r = scenario.run_scenario(LocalScenarioEnvironment(tmp_path / "x.db"))
    assert r.sends == [[Stored()] for _ in scenario.SUBMISSIONS]
    pages = r.pages
    messages = [[x for x in p if isinstance(x, Message)] for p in pages]
    assert [[x.sequence for x in p] for p in messages] == [[1, 2], [3, 4], [5], []]
    assert [p[-1].next_since for p in pages] == [2, 4, 5, 5]
    assert pages[0][-1].has_more and pages[1][-1].has_more and not pages[2][-1].has_more
