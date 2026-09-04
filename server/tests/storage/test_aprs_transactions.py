from pathlib import Path

from openqsp.storage import APRSTransactionSequenceStore, Database


def _store(path: Path) -> APRSTransactionSequenceStore:
    database = Database(path)
    database.initialize()
    return APRSTransactionSequenceStore(database)


def test_transaction_sequence_is_persistent_per_peer(tmp_path: Path) -> None:
    path = tmp_path / "openqsp.db"
    first = _store(path)

    assert first.reserve("EA3GNU") == 0
    assert first.reserve("EA3GNU") == 1
    assert first.reserve("EA3SIL") == 0

    restarted = _store(path)
    assert restarted.reserve("EA3GNU") == 2
    assert restarted.reserve("EA3SIL") == 1


def test_transaction_sequence_wraps_after_255(tmp_path: Path) -> None:
    store = _store(tmp_path / "openqsp.db")

    values = [store.reserve("EA3GNU") for _ in range(257)]

    assert values[0] == 0
    assert values[255] == 255
    assert values[256] == 0
    assert store.next_value("EA3GNU") == 1
