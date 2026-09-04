from pathlib import Path

from openqsp.protocol import GetCapabilities, encode_frame
from openqsp.server import ServerCore
from openqsp.storage import APRSTransactionSequenceStore, Database
from openqsp.transport.aprs import PersistentSelectiveBurstAPRSAdapter


def _adapter(path: Path) -> PersistentSelectiveBurstAPRSAdapter:
    database = Database(path)
    database.initialize()
    return PersistentSelectiveBurstAPRSAdapter(
        ServerCore(),
        service_callsign="OPENQSP",
        transaction_sequence_store=APRSTransactionSequenceStore(database),
    )


def test_q2_transaction_id_continues_after_adapter_restart(tmp_path: Path) -> None:
    path = tmp_path / "openqsp.db"
    frame = encode_frame(GetCapabilities())

    first = _adapter(path)
    assert first.queue_frame("EA3GNU", frame) == "000"
    assert first.queue_frame("EA3SIL", frame) == "000"

    restarted = _adapter(path)
    assert restarted.queue_frame("EA3GNU", frame) == "001"
    assert restarted.queue_frame("EA3SIL", frame) == "001"


def test_q2_transaction_ids_are_reserved_before_transmission(tmp_path: Path) -> None:
    path = tmp_path / "openqsp.db"
    frame = encode_frame(GetCapabilities())

    first = _adapter(path)
    assert first.queue_frame("EA3GNU", frame) == "000"
    # Simulate a crash before poll()/RF transmission by discarding the adapter.

    restarted = _adapter(path)
    assert restarted.queue_frame("EA3GNU", frame) == "001"
