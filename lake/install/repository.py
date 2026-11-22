from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from lake.install.history import initialize_history
from lake.install.rebase import InstalledBase, InstalledRow
from lake.review.journal import initialize_journal
from lake.settle.repository import initialize_receipts


class WarehouseStore:
    def __init__(self, path: str | Path):
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute('PRAGMA foreign_keys = ON')
            self.initialize()
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> WarehouseStore:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def initialize(self) -> None:
        with self.write_transaction() as connection:
            initialize_history(connection)
            connection.execute('''
                CREATE TABLE IF NOT EXISTS active_base (
                    slot INTEGER PRIMARY KEY CHECK (slot = 1),
                    stream TEXT NOT NULL,
                    revision_id TEXT NOT NULL,
                    predecessor TEXT,
                    ordinal INTEGER NOT NULL,
                    issue_id TEXT NOT NULL,
                    default_price TEXT NOT NULL,
                    evidence_digest TEXT NOT NULL
                )
            ''')
            connection.execute('''
                CREATE TABLE IF NOT EXISTS active_rows (
                    position INTEGER PRIMARY KEY,
                    original_id TEXT NOT NULL UNIQUE,
                    station TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    source_price TEXT
                )
            ''')
            initialize_journal(connection)
            initialize_receipts(connection)

    @contextmanager
    def _transaction(self, begin: str):
        self.connection.execute(begin)
        try:
            yield self.connection
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def read_transaction(self):
        return self._transaction('BEGIN')

    def write_transaction(self):
        return self._transaction('BEGIN IMMEDIATE')


def load_base(connection: sqlite3.Connection) -> InstalledBase | None:
    header = connection.execute('SELECT * FROM active_base WHERE slot = 1').fetchone()
    if header is None:
        return None
    rows = connection.execute('''
        SELECT original_id, station, quantity, source_price FROM active_rows ORDER BY position
    ''')
    return InstalledBase(
        header['stream'], header['revision_id'], header['predecessor'], header['ordinal'],
        header['issue_id'], int(header['default_price']), header['evidence_digest'],
        tuple(InstalledRow(row['original_id'], row['station'], int(row['quantity']),
                           None if row['source_price'] is None else int(row['source_price']))
              for row in rows),
    )


def replace_base(connection: sqlite3.Connection, base: InstalledBase) -> None:
    connection.execute('''
        INSERT INTO active_base
            (slot, stream, revision_id, predecessor, ordinal, issue_id, default_price, evidence_digest)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (slot) DO UPDATE SET
            stream = excluded.stream, revision_id = excluded.revision_id,
            predecessor = excluded.predecessor, ordinal = excluded.ordinal,
            issue_id = excluded.issue_id, default_price = excluded.default_price,
            evidence_digest = excluded.evidence_digest
    ''', (base.stream, base.revision_id, base.predecessor, base.ordinal, base.issue_id,
          str(base.default_price), base.evidence_digest))
    connection.execute('DELETE FROM active_rows')
    connection.executemany('''
        INSERT INTO active_rows (position, original_id, station, quantity, source_price)
        VALUES (?, ?, ?, ?, ?)
    ''', ((position, row.original_id, row.station, str(row.quantity),
           None if row.source_price is None else str(row.source_price))
          for position, row in enumerate(base.rows)))
