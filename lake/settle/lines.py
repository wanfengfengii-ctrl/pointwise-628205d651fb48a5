from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lake.install.rebase import InstalledBase
    from lake.review.decisions import Decision


@dataclass(frozen=True)
class SettlementLine:
    original_id: str
    station: str
    quantity: int
    source_price: int | None
    unit_price: int
    amount: int
    price_origin: str
    decision_sequence: int | None


def calculate_lines(base: InstalledBase, decisions: Mapping[str, Decision]) -> tuple[SettlementLine, ...]:
    from lake.review.pricing import resolve_price

    lines = []
    for row in base.rows:
        basis = resolve_price(base, row, decisions.get(row.original_id))
        lines.append(SettlementLine(
            row.original_id, row.station, row.quantity, row.source_price,
            basis.price, row.quantity * basis.price, basis.origin, basis.decision_sequence,
        ))
    return tuple(lines)
