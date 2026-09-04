"""Persistent Q2 transaction allocation for the APRS selective-burst adapter."""

from __future__ import annotations

from openqsp.storage import APRSTransactionSequenceStore

from .carriage import base36
from .selective_burst_guarded import APRSAdapter as _BaseSelectiveBurstAPRSAdapter


class APRSAdapter(_BaseSelectiveBurstAPRSAdapter):
    """Selective-burst adapter with durable per-peer transaction IDs.

    When a persistent sequence store is supplied, each Q2 transaction byte is
    reserved in SQLite before it is returned to the caller. This mirrors the
    client-side reservation semantics: a process crash after allocation cannot
    make the next server process reuse an ID that may already have reached RF.
    """

    def __init__(
        self,
        *args,
        transaction_sequence_store: APRSTransactionSequenceStore | None = None,
        **kwargs,
    ) -> None:
        self._transaction_sequence_store = transaction_sequence_store
        super().__init__(*args, **kwargs)

    def _allocate(self, peer: str, *, transaction: bool) -> str:
        store = self._transaction_sequence_store
        if not transaction or store is None:
            return super()._allocate(peer, transaction=transaction)

        active = self._active_transactions(peer)
        for _ in range(256):
            value = store.reserve(peer)
            # Keep the inherited in-memory counter coherent for diagnostics and
            # for callers that inspect it, although persistent allocation is
            # authoritative while the store is configured.
            self._next_transaction[peer] = (value + 1) & 0xFF
            candidate = base36(value, 3)
            if candidate not in active:
                return candidate
        raise OverflowError("peer Q2 transaction ID space exhausted")
