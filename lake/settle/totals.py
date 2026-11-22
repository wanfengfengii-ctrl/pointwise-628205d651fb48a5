from collections.abc import Iterable
from dataclasses import dataclass

from lake.settle.lines import SettlementLine


@dataclass(frozen=True)
class StationTotal:
    station: str
    amount: int


def summarize_stations(lines: Iterable[SettlementLine]) -> tuple[StationTotal, ...]:
    amounts = {}
    for line in lines:
        amounts[line.station] = amounts.get(line.station, 0) + line.amount
    return tuple(StationTotal(station, amount) for station, amount in sorted(amounts.items()))


def reconcile_totals(lines: Iterable[SettlementLine], stations: Iterable[StationTotal]) -> None:
    verified = {}
    original_ids = set()
    for line in lines:
        if line.original_id in original_ids:
            raise ValueError(f'duplicate settlement line: {line.original_id}')
        original_ids.add(line.original_id)
        if any(type(value) is not int for value in (line.quantity, line.unit_price, line.amount)):
            raise ValueError(f'non-integer settlement line: {line.original_id}')
        amount = line.quantity * line.unit_price
        if amount != line.amount:
            raise ValueError(f'line amount mismatch: {line.original_id}')
        verified[line.station] = verified.get(line.station, 0) + amount
    supplied = {}
    for total in stations:
        if total.station in supplied or type(total.amount) is not int:
            raise ValueError(f'invalid station total: {total.station}')
        supplied[total.station] = total.amount
    if supplied != verified:
        raise ValueError('station reconciliation mismatch')
