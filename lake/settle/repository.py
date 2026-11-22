from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING
from uuid import uuid4

from lake.settle.lines import SettlementLine
from lake.settle.totals import StationTotal

if TYPE_CHECKING:
    from lake.settle.publish import SettlementPreview


def initialize_receipts(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS receipts (
            receipt_id TEXT PRIMARY KEY,
            stream TEXT NOT NULL,
            revision_id TEXT NOT NULL REFERENCES installation_history(revision_id),
            issue_id TEXT NOT NULL,
            default_price TEXT NOT NULL
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS receipt_lines (
            receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id),
            position INTEGER NOT NULL,
            original_id TEXT NOT NULL,
            station TEXT NOT NULL,
            quantity TEXT NOT NULL,
            source_price TEXT,
            unit_price TEXT NOT NULL,
            amount TEXT NOT NULL,
            price_origin TEXT NOT NULL,
            decision_sequence INTEGER REFERENCES review_journal(sequence),
            PRIMARY KEY (receipt_id, position),
            UNIQUE (receipt_id, original_id)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS receipt_stations (
            receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id),
            station TEXT NOT NULL,
            amount TEXT NOT NULL,
            PRIMARY KEY (receipt_id, station)
        )
    ''')


def save_receipt(connection: sqlite3.Connection, snapshot: SettlementPreview) -> str:
    receipt_id = uuid4().hex
    connection.execute('''
        INSERT INTO receipts (receipt_id, stream, revision_id, issue_id, default_price)
        VALUES (?, ?, ?, ?, ?)
    ''', (receipt_id, snapshot.stream, snapshot.revision_id, snapshot.issue_id, str(snapshot.default_price)))
    connection.executemany('''
        INSERT INTO receipt_lines (receipt_id, position, original_id, station, quantity, source_price,
                                   unit_price, amount, price_origin, decision_sequence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        (receipt_id, position, line.original_id, line.station, str(line.quantity),
         None if line.source_price is None else str(line.source_price), str(line.unit_price),
         str(line.amount), line.price_origin, line.decision_sequence)
        for position, line in enumerate(snapshot.lines)
    ))
    connection.executemany('''
        INSERT INTO receipt_stations (receipt_id, station, amount) VALUES (?, ?, ?)
    ''', ((receipt_id, total.station, str(total.amount)) for total in snapshot.stations))
    return receipt_id


def load_receipt(
    connection: sqlite3.Connection, receipt_id: str,
) -> tuple[sqlite3.Row, tuple[SettlementLine, ...], tuple[StationTotal, ...]] | None:
    header = connection.execute('SELECT * FROM receipts WHERE receipt_id = ?', (receipt_id,)).fetchone()
    if header is None:
        return None
    rows = connection.execute('''
        SELECT original_id, station, quantity, source_price, unit_price, amount, price_origin, decision_sequence
        FROM receipt_lines WHERE receipt_id = ? ORDER BY position
    ''', (receipt_id,))
    lines = tuple(
        SettlementLine(row['original_id'], row['station'], int(row['quantity']),
                       None if row['source_price'] is None else int(row['source_price']),
                       int(row['unit_price']), int(row['amount']), row['price_origin'], row['decision_sequence'])
        for row in rows
    )
    totals = connection.execute('''
        SELECT station, amount FROM receipt_stations WHERE receipt_id = ? ORDER BY station
    ''', (receipt_id,))
    return header, lines, tuple(StationTotal(row['station'], int(row['amount'])) for row in totals)
