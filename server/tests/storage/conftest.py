import pytest
from openqsp.storage import Database


@pytest.fixture
def database(tmp_path):
    d = Database(tmp_path / "node.db")
    d.initialize()
    return d
