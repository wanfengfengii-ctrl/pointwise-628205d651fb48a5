from dataclasses import dataclass

from lake.install.rebase import InstalledBase, InstalledRow
from lake.review.decisions import Decision


@dataclass(frozen=True)
class PriceBasis:
    price: int
    origin: str
    decision_sequence: int | None = None


def resolve_price(base: InstalledBase, row: InstalledRow, confirmation: Decision | None) -> PriceBasis:
    if confirmation is not None and confirmation.price is not None:
        return PriceBasis(confirmation.price, 'confirmation', confirmation.sequence)
    if row.source_price is not None:
        return PriceBasis(row.source_price, 'source_explicit')
    return PriceBasis(base.default_price, 'source_default')
