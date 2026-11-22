import sqlite3


def initialize_journal(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS review_journal (
            sequence INTEGER PRIMARY KEY,
            stream TEXT NOT NULL,
            original_id TEXT NOT NULL,
            revision_id TEXT NOT NULL REFERENCES installation_history(revision_id),
            price TEXT
        )
    ''')
    connection.execute('''
        CREATE INDEX IF NOT EXISTS review_by_original
        ON review_journal (stream, original_id, sequence)
    ''')


def append_decision(
    connection: sqlite3.Connection, stream: str, original_id: str,
    revision_id: str, price: int | None,
) -> int:
    cursor = connection.execute('''
        INSERT INTO review_journal (stream, original_id, revision_id, price)
        VALUES (?, ?, ?, ?)
    ''', (stream, original_id, revision_id, None if price is None else str(price)))
    return cursor.lastrowid


def load_latest_decisions(connection: sqlite3.Connection, stream: str) -> list[sqlite3.Row]:
    return connection.execute('''
        SELECT journal.sequence, journal.stream, journal.original_id, journal.revision_id, journal.price
        FROM review_journal AS journal
        JOIN (
            SELECT MAX(sequence) AS sequence
            FROM review_journal WHERE stream = ? GROUP BY original_id
        ) AS latest ON journal.sequence = latest.sequence
        ORDER BY journal.original_id
    ''', (stream,)).fetchall()
