"""Run the existing scenario assertions through the real TCP stack."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import pytest

TOOLS_ROOT = Path(__file__).parents[3] / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))
from scenario_environment import RemoteScenarioEnvironment

E2E_ROOT = Path(__file__).parent
CASES = (
    (
        "test_multi_user_private_message.py",
        "test_two_users_exchange_one_private_message_through_real_stack",
    ),
    (
        "test_empty_mailbox_sync.py",
        "test_empty_mailbox_sync_preserves_completed_cursor",
    ),
    (
        "test_incremental_mailbox_sync.py",
        "test_mailbox_sync_reuses_end_cursors_without_duplicates",
    ),
    (
        "test_mailbox_pagination.py",
        "test_mailbox_paginates_with_end_cursors_and_interleaved_sequences",
    ),
    ("test_bulletin_sync_retrieval.py", "test_bulletin_sync_retrieval_and_resume"),
    (
        "test_node_restart_persistence.py",
        "test_private_mailbox_sync_recovers_across_node_restart",
    ),
    ("test_milestone4_conformance.py", "test_milestone4_complete_local_node_workflow"),
)


@pytest.mark.parametrize(("filename", "test_name"), CASES)
def test_existing_scenario_through_remote_tcp(tmp_path, filename, test_name):
    """Reuse each local test's exact semantic assertions, changing only its seam."""
    spec = spec_from_file_location(f"remote_{filename[:-3]}", E2E_ROOT / filename)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    environments = []

    def factory(path):
        environment = RemoteScenarioEnvironment(path)
        environments.append(environment)
        return environment

    module.LocalScenarioEnvironment = factory
    try:
        getattr(module, test_name)(tmp_path)
    finally:
        for environment in environments:
            environment.close()
