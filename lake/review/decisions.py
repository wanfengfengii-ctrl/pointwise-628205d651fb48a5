import sqlite3
from dataclasses import dataclass

from lake.install.catalog import load_active_base
from lake.install.rebase import InstalledBase
from lake.install.repository import WarehouseStore
from lake.review.confirm import record_confirmation
from lake.review.journal import load_latest_decisions
from lake.review.withdraw import record_withdrawal
from lake.settle.signoff import evaluate_pending_signoffs
from lake.source.rows import require_identifier


@dataclass(frozen=True)
class Decision:
    sequence: int
    stream: str
    original_id: str
    revision_id: str
    price: int | None


def decide(
    store: WarehouseStore, original_id: str, *, action: str, price: int | None = None,
) -> Decision:
    original_id = require_identifier(original_id, 'original_id')
    if action not in ('confirm', 'withdraw'):
        raise ValueError('action must be confirm or withdraw')
    if action == 'withdraw' and price is not None:
        raise ValueError('withdrawal does not take a price')
    with store.write_transaction() as connection:
        base = load_active_base(connection)
        if base is None:
            raise RuntimeError('no active base')
        if all(row.original_id != original_id for row in base.rows):
            raise KeyError(f'unknown original_id: {original_id}')
        if action == 'confirm':
            sequence = record_confirmation(connection, base, original_id, price)
        else:
            sequence = record_withdrawal(connection, base, original_id)
        decision = Decision(sequence, base.stream, original_id, base.revision_id, price)
        evaluate_pending_signoffs(connection, 'review', sequence)
    return decision


def load_effective_decisions(
    connection: sqlite3.Connection, base: InstalledBase,
) -> dict[str, Decision]:
    installed_ids = {row.original_id for row in base.rows}
    return {
        row['original_id']: Decision(row['sequence'], row['stream'], row['original_id'],
                                     row['revision_id'], int(row['price']))
        for row in load_latest_decisions(connection, base.stream)
        if row['price'] is not None and row['original_id'] in installed_ids
    }
