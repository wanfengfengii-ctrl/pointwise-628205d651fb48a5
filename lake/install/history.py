import sqlite3
from dataclasses import dataclass

from lake.install.rebase import InstalledBase


@dataclass(frozen=True)
class Installation:
    stream: str
    revision_id: str
    predecessor: str | None
    ordinal: int
    issue_id: str


def initialize_history(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS installation_history (
            stream TEXT NOT NULL,
            revision_id TEXT PRIMARY KEY,
            predecessor TEXT REFERENCES installation_history(revision_id),
            ordinal INTEGER NOT NULL,
            issue_id TEXT NOT NULL UNIQUE,
            UNIQUE (stream, ordinal)
        )
    ''')


def append_installation(connection: sqlite3.Connection, base: InstalledBase) -> None:
    connection.execute('''
        INSERT INTO installation_history (stream, revision_id, predecessor, ordinal, issue_id)
        VALUES (?, ?, ?, ?, ?)
    ''', (base.stream, base.revision_id, base.predecessor, base.ordinal, base.issue_id))


def read_installation(connection: sqlite3.Connection, revision_id: str) -> Installation | None:
    row = connection.execute('''
        SELECT stream, revision_id, predecessor, ordinal, issue_id
        FROM installation_history WHERE revision_id = ?
    ''', (revision_id,)).fetchone()
    if row is None:
        return None
    return Installation(*row)
