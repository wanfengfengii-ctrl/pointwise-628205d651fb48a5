import sqlite3
from dataclasses import dataclass

from lake.install.catalog import load_active_base
from lake.install.repository import WarehouseStore
from lake.review.decisions import load_effective_decisions
from lake.settle.lines import SettlementLine, calculate_lines
from lake.settle.repository import save_receipt
from lake.settle.signoff import sign, stage, status
from lake.settle.totals import StationTotal, reconcile_totals, summarize_stations


@dataclass(frozen=True)
class SettlementPreview:
    stream: str
    revision_id: str
    issue_id: str
    default_price: int
    lines: tuple[SettlementLine, ...]
    stations: tuple[StationTotal, ...]

    @property
    def total(self) -> int:
        return sum(station.amount for station in self.stations)


def _calculate_current(connection: sqlite3.Connection) -> SettlementPreview:
    base = load_active_base(connection)
    if base is None:
        raise RuntimeError('no active base')
    decisions = load_effective_decisions(connection, base)
    lines = calculate_lines(base, decisions)
    return SettlementPreview(
        base.stream, base.revision_id, base.issue_id, base.default_price, lines, summarize_stations(lines),
    )


def preview(store: WarehouseStore) -> SettlementPreview:
    with store.read_transaction() as connection:
        return _calculate_current(connection)


def _publish_snapshot(connection: sqlite3.Connection, snapshot: SettlementPreview) -> str:
    reconcile_totals(snapshot.lines, snapshot.stations)
    return save_receipt(connection, snapshot)


def publish(store: WarehouseStore) -> str:
    with store.write_transaction() as connection:
        receipt_id = _publish_snapshot(connection, _calculate_current(connection))
    return receipt_id
