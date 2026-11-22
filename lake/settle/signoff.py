from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from lake.settle.lines import SettlementLine, calculate_lines
from lake.settle.repository import save_receipt
from lake.settle.totals import StationTotal, reconcile_totals, summarize_stations
from lake.source.rows import require_identifier

if TYPE_CHECKING:
    from lake.install.rebase import InstalledBase
    from lake.install.repository import WarehouseStore


@dataclass(frozen=True)
class SignoffTicket:
    ticket_id: str
    station: str
    state: str
    cause_kind: str | None
    cause_revision_id: str | None
    cause_sequence: int | None
    receipt_id: str | None


@dataclass(frozen=True)
class StationSnapshot:
    stream: str
    revision_id: str
    issue_id: str
    default_price: int
    lines: tuple[SettlementLine, ...]
    stations: tuple[StationTotal, ...]


def initialize_signoff(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS signoff_tickets (
            ticket_id TEXT PRIMARY KEY,
            station TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('pending', 'invalidated', 'signed')),
            cause_kind TEXT,
            cause_revision_id TEXT,
            cause_sequence INTEGER,
            receipt_id TEXT REFERENCES receipts(receipt_id)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS signoff_lines (
            ticket_id TEXT NOT NULL REFERENCES signoff_tickets(ticket_id),
            position INTEGER NOT NULL,
            original_id TEXT NOT NULL,
            quantity TEXT NOT NULL,
            unit_price TEXT NOT NULL,
            PRIMARY KEY (ticket_id, position)
        )
    ''')


def _current_base_and_lines(
    connection: sqlite3.Connection,
) -> tuple[InstalledBase | None, tuple[SettlementLine, ...] | None]:
    # Imported lazily: lake.install.repository creates these signoff tables and
    # lake.review.decisions evaluates tickets, so both import this module.
    from lake.install.repository import load_base
    from lake.review.decisions import load_effective_decisions

    base = load_base(connection)
    if base is None:
        return None, None
    return base, calculate_lines(base, load_effective_decisions(connection, base))


def _station_entries(
    lines: tuple[SettlementLine, ...], station: str,
) -> tuple[tuple[str, int, int], ...]:
    return tuple(
        (line.original_id, line.quantity, line.unit_price)
        for line in lines
        if line.station == station
    )


def _load_ticket(connection: sqlite3.Connection, ticket_id: str) -> SignoffTicket | None:
    row = connection.execute(
        'SELECT * FROM signoff_tickets WHERE ticket_id = ?', (ticket_id,),
    ).fetchone()
    if row is None:
        return None
    return SignoffTicket(
        row['ticket_id'], row['station'], row['state'], row['cause_kind'],
        row['cause_revision_id'], row['cause_sequence'], row['receipt_id'],
    )


def _staged_entries(
    connection: sqlite3.Connection, ticket_id: str,
) -> tuple[tuple[str, int, int], ...]:
    rows = connection.execute('''
        SELECT original_id, quantity, unit_price FROM signoff_lines
        WHERE ticket_id = ? ORDER BY position
    ''', (ticket_id,))
    return tuple(
        (row['original_id'], int(row['quantity']), int(row['unit_price'])) for row in rows
    )


def _insert_ticket(
    connection: sqlite3.Connection, ticket_id: str, station: str,
    entries: tuple[tuple[str, int, int], ...],
) -> None:
    connection.execute(
        "INSERT INTO signoff_tickets (ticket_id, station, state) VALUES (?, ?, 'pending')",
        (ticket_id, station),
    )
    connection.executemany('''
        INSERT INTO signoff_lines (ticket_id, position, original_id, quantity, unit_price)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        (ticket_id, position, original_id, str(quantity), str(unit_price))
        for position, (original_id, quantity, unit_price) in enumerate(entries)
    ))


def evaluate_pending_signoffs(
    connection: sqlite3.Connection, cause_kind: str, cause_value: object,
) -> None:
    """Invalidate pending tickets whose station list deviates after a ledger change.

    Runs inside the install/review write transaction, so a failed commit rolls
    the invalidation back together with the ledger change. Only the first
    deviating commit is recorded; restored lists never clear the first cause.
    """
    base, lines = _current_base_and_lines(connection)
    if base is None:
        return
    pending = connection.execute('''
        SELECT ticket_id, station FROM signoff_tickets WHERE state = 'pending' ORDER BY ticket_id
    ''').fetchall()
    if not pending:
        return
    current: dict[str, list[tuple[str, int, int]]] = {}
    for line in lines:
        current.setdefault(line.station, []).append(
            (line.original_id, line.quantity, line.unit_price)
        )
    for row in pending:
        staged = _staged_entries(connection, row['ticket_id'])
        if current.get(row['station'], []) != list(staged):
            connection.execute('''
                UPDATE signoff_tickets
                SET state = 'invalidated', cause_kind = ?,
                    cause_revision_id = ?, cause_sequence = ?
                WHERE ticket_id = ? AND state = 'pending'
            ''', (
                cause_kind,
                cause_value if cause_kind == 'install' else None,
                cause_value if cause_kind == 'review' else None,
                row['ticket_id'],
            ))


def stage(
    store: WarehouseStore, ticket_id: str, station: str,
) -> tuple[tuple[str, int, int], ...]:
    ticket_id = require_identifier(ticket_id, 'ticket_id')
    station = require_identifier(station, 'station')
    with store.write_transaction() as connection:
        ticket = _load_ticket(connection, ticket_id)
        if ticket is not None:
            if ticket.station != station:
                raise ValueError(
                    f'ticket {ticket_id} is already bound to station {ticket.station}'
                )
            return _staged_entries(connection, ticket_id)
        base, lines = _current_base_and_lines(connection)
        if base is None:
            raise RuntimeError('no active base')
        entries = _station_entries(lines, station)
        if not entries:
            raise KeyError(f'unknown station: {station}')
        _insert_ticket(connection, ticket_id, station, entries)
        return entries


def status(store: WarehouseStore, ticket_id: str) -> dict:
    ticket_id = require_identifier(ticket_id, 'ticket_id')
    with store.read_transaction() as connection:
        ticket = _load_ticket(connection, ticket_id)
    if ticket is None:
        raise KeyError(f'unknown signoff ticket: {ticket_id}')
    cause = None
    if ticket.state == 'invalidated':
        if ticket.cause_kind == 'install':
            cause = {'kind': 'install', 'revision_id': ticket.cause_revision_id}
        else:
            cause = {'kind': 'review', 'sequence': ticket.cause_sequence}
    return {'state': ticket.state, 'cause': cause, 'receipt_id': ticket.receipt_id}


def sign(store: WarehouseStore, ticket_id: str) -> str:
    ticket_id = require_identifier(ticket_id, 'ticket_id')
    with store.write_transaction() as connection:
        ticket = _load_ticket(connection, ticket_id)
        if ticket is None:
            raise KeyError(f'unknown signoff ticket: {ticket_id}')
        if ticket.state == 'signed':
            return ticket.receipt_id
        if ticket.state == 'invalidated':
            raise ValueError(f'signoff ticket is invalidated: {ticket_id}')
        base, lines = _current_base_and_lines(connection)
        if base is None:
            raise RuntimeError('no active base')
        station_lines = tuple(line for line in lines if line.station == ticket.station)
        snapshot = StationSnapshot(
            base.stream, base.revision_id, base.issue_id, base.default_price,
            station_lines, summarize_stations(station_lines),
        )
        reconcile_totals(snapshot.lines, snapshot.stations)
        receipt_id = save_receipt(connection, snapshot)
        connection.execute('''
            UPDATE signoff_tickets SET state = 'signed', receipt_id = ?
            WHERE ticket_id = ? AND state = 'pending'
        ''', (receipt_id, ticket_id))
    return receipt_id
