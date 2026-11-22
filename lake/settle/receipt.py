from dataclasses import dataclass

from lake.install.repository import WarehouseStore
from lake.settle.lines import SettlementLine
from lake.settle.repository import load_receipt
from lake.settle.totals import StationTotal
from lake.source.rows import require_identifier


@dataclass(frozen=True)
class SettlementReceipt:
    receipt_id: str
    stream: str
    revision_id: str
    issue_id: str
    default_price: int
    lines: tuple[SettlementLine, ...]
    stations: tuple[StationTotal, ...]

    @property
    def total(self) -> int:
        return sum(station.amount for station in self.stations)


def read(store: WarehouseStore, receipt_id: str) -> SettlementReceipt:
    receipt_id = require_identifier(receipt_id, 'receipt_id')
    with store.read_transaction() as connection:
        loaded = load_receipt(connection, receipt_id)
    if loaded is None:
        raise KeyError(f'unknown settlement receipt: {receipt_id}')
    header, lines, stations = loaded
    return SettlementReceipt(
        receipt_id, header['stream'], header['revision_id'], header['issue_id'],
        int(header['default_price']), lines, stations,
    )
