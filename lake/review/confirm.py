import sqlite3

from lake.install.rebase import InstalledBase
from lake.review.journal import append_decision
from lake.source.tariffs import validate_integer_price


def record_confirmation(
    connection: sqlite3.Connection, base: InstalledBase, original_id: str, price: object,
) -> int:
    value = validate_integer_price(price, 'confirmation price')
    return append_decision(connection, base.stream, original_id, base.revision_id, value)
