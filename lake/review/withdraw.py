import sqlite3

from lake.install.rebase import InstalledBase
from lake.review.journal import append_decision


def record_withdrawal(connection: sqlite3.Connection, base: InstalledBase, original_id: str) -> int:
    return append_decision(connection, base.stream, original_id, base.revision_id, None)
