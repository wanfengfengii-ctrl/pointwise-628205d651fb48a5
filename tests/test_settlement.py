from dataclasses import replace

from lake.exchange.issue import issue
from lake.install.catalog import install
from lake.review.decisions import decide
from lake.settle.publish import _publish_snapshot, preview, publish
from lake.settle.receipt import read
from lake.settle.totals import StationTotal
from lake.source.revisions import freeze
from lake.source.rows import SourceRow
from lake.source.store import SourceStore
from tests import LakeCase, ROWS


class SettlementTests(LakeCase):
    def install_multistation(self):
        rows = tuple(replace(row, quantity=quantity) for row, quantity in zip(ROWS, (3, 2, 4)))
        first, _ = self.issued_pair(rows)
        return install(self.warehouse, first)

    def test_fixed_receipt(self):
        first, second = self.issued_pair()
        first_revision = install(self.warehouse, first)
        receipt = publish(self.warehouse)
        install(self.warehouse, second)
        self.assertEqual(preview(self.warehouse).total, 19)
        self.reopen_warehouse()
        stored = read(self.warehouse, receipt)
        self.assertEqual(stored.revision_id, first_revision)
        self.assertEqual([line.amount for line in stored.lines], [5, 5, 5])
        self.assertEqual(stored.stations, (StationTotal('east', 10), StationTotal('west', 5)))
        self.assertEqual(stored.total, 15)

    def test_quantity_and_station(self):
        self.install_multistation()
        current = preview(self.warehouse)
        self.assertEqual(self.receipt_ids(), set())
        stored = read(self.warehouse, publish(self.warehouse))
        for result in (current, stored):
            self.assertEqual([(line.original_id, line.amount) for line in result.lines],
                             [('jia', 15), ('yi', 10), ('bing', 20)])
            self.assertEqual(result.stations, (StationTotal('east', 25), StationTotal('west', 20)))
            self.assertEqual(result.total, 45)

    def test_history_after_withdrawal(self):
        first, second = self.issued_pair()
        r1 = install(self.warehouse, first)
        receipt1 = publish(self.warehouse)
        decide(self.warehouse, 'yi', action='confirm', price=5)
        r2 = install(self.warehouse, second)
        receipt2 = publish(self.warehouse)
        signed = (read(self.warehouse, receipt1), read(self.warehouse, receipt2))
        self.assertEqual((signed[0].total, signed[1].total), (15, 17))
        decide(self.warehouse, 'yi', action='withdraw')
        self.reopen_warehouse()
        self.assertEqual(preview(self.warehouse).total, 19)
        restored = (read(self.warehouse, receipt1), read(self.warehouse, receipt2))
        self.assertEqual(restored, signed)
        self.assertEqual([receipt.revision_id for receipt in restored], [r1, r2])
        self.assertEqual([[line.amount for line in receipt.lines] for receipt in restored],
                         [[5, 5, 5], [5, 5, 7]])
        self.assertEqual(restored[1].lines[1].price_origin, 'confirmation')

    def test_warehouse_reopen(self):
        first, second = self.external_pair()
        install(self.warehouse, first)
        decide(self.warehouse, 'yi', action='confirm', price=6)
        install(self.warehouse, second)
        receipt = publish(self.warehouse)
        self.reopen_warehouse()
        self.warehouse.initialize()
        current = preview(self.warehouse)
        self.assertEqual(current.revision_id, 'outside-r2')
        self.assertEqual([line.amount for line in current.lines], [5, 6, 7])
        self.assertEqual(read(self.warehouse, receipt).lines, current.lines)
        self.assertEqual(self.receipt_ids(), {receipt})

    def test_not_ready(self):
        for operation in (preview, publish):
            with self.subTest(operation=operation.__name__), self.assertRaisesRegex(RuntimeError, 'no active base'):
                operation(self.warehouse)
        self.assertEqual(self.receipt_ids(), set())

    def test_unknown_receipt(self):
        first, _ = self.external_pair()
        install(self.warehouse, first)
        known = publish(self.warehouse)
        with self.assertRaisesRegex(KeyError, 'unknown settlement receipt'):
            read(self.warehouse, 'missing')
        self.assertEqual(read(self.warehouse, known).total, 15)

    def test_failed_publish(self):
        first, second = self.external_pair()
        install(self.warehouse, first)
        receipt = publish(self.warehouse)
        saved = read(self.warehouse, receipt)
        install(self.warehouse, second)
        self.deny_commit_on_insert(self.warehouse, 'receipts')
        self.assert_commit_refused(self.warehouse, publish)
        self.reopen_warehouse()
        self.assertEqual(self.receipt_ids(), {receipt})
        self.assertEqual(read(self.warehouse, receipt), saved)
        self.assertEqual(preview(self.warehouse).total, 19)
        self.allow_commits(self.warehouse)
        later = publish(self.warehouse)
        self.assertEqual(read(self.warehouse, later).total, 19)

    def test_station_reconciliation(self):
        self.install_multistation()
        receipt = publish(self.warehouse)
        original = read(self.warehouse, receipt)
        snapshot = preview(self.warehouse)
        swapped = replace(snapshot, stations=(StationTotal('east', 20), StationTotal('west', 25)))
        self.assertEqual(snapshot.total, swapped.total)
        with self.assertRaisesRegex(ValueError, 'station reconciliation mismatch'):
            with self.warehouse.write_transaction() as connection:
                _publish_snapshot(connection, swapped)
        self.assertEqual(self.receipt_ids(), {receipt})
        self.assertEqual(read(self.warehouse, receipt), original)

    def test_line_reconciliation(self):
        self.install_multistation()
        snapshot = preview(self.warehouse)
        lines = (replace(snapshot.lines[0], amount=14), replace(snapshot.lines[1], amount=11), snapshot.lines[2])
        with self.assertRaisesRegex(ValueError, 'line amount mismatch: jia'):
            with self.warehouse.write_transaction() as connection:
                _publish_snapshot(connection, replace(snapshot, lines=lines))
        self.assertEqual(self.receipt_ids(), set())

    def test_exact_integers_and_zero_station(self):
        big = 2 ** 80
        rows = (SourceRow('quantity', 'east', big, -2), SourceRow('zero', 'west', big, 0))
        with SourceStore(self.source_path) as source:
            revision = freeze(source, 'day', None, 5, rows)
            sealed = issue(source, revision)
        install(self.warehouse, sealed)
        receipt = publish(self.warehouse)
        self.reopen_warehouse()
        saved = read(self.warehouse, receipt)
        self.assertEqual([line.quantity for line in saved.lines], [big, big])
        self.assertEqual(saved.stations, (StationTotal('east', -(2 ** 81)), StationTotal('west', 0)))

    def test_empty_snapshot(self):
        first, _ = self.issued_pair(())
        install(self.warehouse, first)
        saved = read(self.warehouse, publish(self.warehouse))
        self.assertEqual((saved.lines, saved.stations, saved.total), ((), (), 0))
