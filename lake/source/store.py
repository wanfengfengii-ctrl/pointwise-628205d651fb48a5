from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lake.source.revisions import FrozenRevision


class SourceStore:
    def __init__(self, path: str | Path):
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute('PRAGMA foreign_keys = ON')
            self.initialize()
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> SourceStore:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def initialize(self) -> None:
        with self.write_transaction() as connection:
            connection.execute('''
                CREATE TABLE IF NOT EXISTS source_revisions (
                    revision_id TEXT PRIMARY KEY,
                    stream TEXT NOT NULL,
                    predecessor TEXT REFERENCES source_revisions(revision_id),
                    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
                    default_price TEXT NOT NULL,
                    row_count INTEGER NOT NULL CHECK (row_count >= 0),
                    UNIQUE (stream, ordinal)
                )
            ''')
            connection.execute('''
                CREATE TABLE IF NOT EXISTS source_rows (
                    revision_id TEXT NOT NULL REFERENCES source_revisions(revision_id),
                    position INTEGER NOT NULL,
                    original_id TEXT NOT NULL,
                    station TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    source_price TEXT,
                    PRIMARY KEY (revision_id, position),
                    UNIQUE (revision_id, original_id)
                )
            ''')
            connection.execute('''
                CREATE TABLE IF NOT EXISTS source_heads (
                    stream TEXT PRIMARY KEY,
                    revision_id TEXT NOT NULL REFERENCES source_revisions(revision_id)
                )
            ''')

    @contextmanager
    def write_transaction(self):
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            yield self.connection
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def load_head(self, stream: str) -> sqlite3.Row | None:
        return self.connection.execute('''
            SELECT revisions.revision_id, revisions.ordinal
            FROM source_heads AS heads
            JOIN source_revisions AS revisions ON revisions.revision_id = heads.revision_id
            WHERE heads.stream = ?
        ''', (stream,)).fetchone()

    def load_revision(self, revision_id: str) -> tuple[sqlite3.Row, list[sqlite3.Row]] | None:
        header = self.connection.execute(
            'SELECT * FROM source_revisions WHERE revision_id = ?', (revision_id,)
        ).fetchone()
        if header is None:
            return None
        rows = self.connection.execute('''
            SELECT position, original_id, station, quantity, source_price
            FROM source_rows WHERE revision_id = ? ORDER BY position
        ''', (revision_id,)).fetchall()
        return header, rows

    def save_revision(self, revision: FrozenRevision) -> None:
        if not self.connection.in_transaction:
            raise RuntimeError('saving a revision requires a source transaction')
        self.connection.execute('''
            INSERT INTO source_revisions
                (revision_id, stream, predecessor, ordinal, default_price, row_count)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (revision.revision_id, revision.stream, revision.predecessor, revision.ordinal,
              str(revision.default_price), len(revision.rows)))
        self.connection.executemany('''
            INSERT INTO source_rows
                (revision_id, position, original_id, station, quantity, source_price)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            (revision.revision_id, position, row.original_id, row.station, str(row.quantity),
             None if row.source_price is None else str(row.source_price))
            for position, row in enumerate(revision.rows)
        ))
        self.connection.execute('''
            INSERT INTO source_heads (stream, revision_id) VALUES (?, ?)
            ON CONFLICT (stream) DO UPDATE SET revision_id = excluded.revision_id
        ''', (revision.stream, revision.revision_id))
