from lake.install.catalog import install
from lake.review.decisions import decide
from lake.settle.publish import preview, publish
from lake.settle.receipt import read
from tests import LakeCase


class ReviewTests(LakeCase):
    def test_equal_value_confirmation(self):
        first, second = self.issued_pair()
        initial_revision = install(self.warehouse, first)
        initial_receipt = publish(self.warehouse)
        self.assertEqual(read(self.warehouse, initial_receipt).total, 15)
        decision = decide(self.warehouse, 'yi', action='confirm', price=5)
        self.assertEqual(decision.revision_id, initial_revision)
        install(self.warehouse, second)
        current = preview(self.warehouse)
        actual = [line.amount for line in current.lines]
        self.assertEqual(actual, [5, 5, 7], f'PRICE_ORIGIN_DRIFT actual={actual} total={current.total}')
        self.assertEqual(current.total, 17)
        self.assertEqual([line.price_origin for line in current.lines],
                         ['source_explicit', 'confirmation', 'source_default'])
        self.assertEqual(current.lines[1].decision_sequence, decision.sequence)

    def test_external_bundles(self):
        first, second = self.external_pair()
        install(self.warehouse, first)
        decide(self.warehouse, 'yi', action='confirm', price=5)
        install(self.warehouse, second)
        self.reopen_warehouse()
        prepared = preview(self.warehouse)
        self.assertEqual(prepared.revision_id, 'outside-r2')
        self.assertEqual([line.amount for line in prepared.lines], [5, 5, 7])
        self.assertEqual(prepared.total, 17)

    def test_reconfirm(self):
        first, second = self.issued_pair()
        install(self.warehouse, first)
        previous = decide(self.warehouse, 'yi', action='confirm', price=5)
        latest = decide(self.warehouse, 'yi', action='confirm', price=6)
        self.assertGreater(latest.sequence, previous.sequence)
        install(self.warehouse, second)
        self.reopen_warehouse()
        current = preview(self.warehouse)
        self.assertEqual([line.amount for line in current.lines], [5, 6, 7])
        self.assertEqual(current.lines[1].decision_sequence, latest.sequence)
        with self.warehouse.read_transaction() as connection:
            prices = connection.execute('SELECT price FROM review_journal ORDER BY sequence').fetchall()
        self.assertEqual([int(row[0]) for row in prices], [5, 6])

    def test_invalid_decision(self):
        first, _ = self.external_pair()
        install(self.warehouse, first)
        original = decide(self.warehouse, 'yi', action='confirm', price=6)
        before = preview(self.warehouse)
        with self.assertRaisesRegex(KeyError, 'unknown original_id'):
            decide(self.warehouse, 'none', action='confirm', price=5)
        for invalid in (None, True, 7.0, '7'):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'must be an integer'):
                decide(self.warehouse, 'yi', action='confirm', price=invalid)
        with self.assertRaisesRegex(ValueError, 'does not take a price'):
            decide(self.warehouse, 'yi', action='withdraw', price=5)
        self.deny_commit_on_insert(self.warehouse, 'review_journal')
        self.assert_commit_refused(self.warehouse, decide, 'yi', action='confirm', price=9)
        self.assert_commit_refused(self.warehouse, decide, 'yi', action='withdraw')
        self.reopen_warehouse()
        self.assertEqual(preview(self.warehouse), before)
        self.assertEqual(preview(self.warehouse).lines[1].decision_sequence, original.sequence)
        with self.warehouse.read_transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM review_journal').fetchone()[0], 1)

    def test_withdraw_uses_current_base(self):
        first, second = self.issued_pair()
        install(self.warehouse, first)
        decide(self.warehouse, 'yi', action='confirm', price=5)
        r2 = install(self.warehouse, second)
        self.reopen_warehouse()
        self.assertEqual(preview(self.warehouse).total, 17)
        withdrawn = decide(self.warehouse, 'yi', action='withdraw')
        self.assertEqual((withdrawn.price, withdrawn.revision_id), (None, r2))
        self.reopen_warehouse()
        current = preview(self.warehouse)
        self.assertEqual([line.amount for line in current.lines], [5, 7, 7])
        self.assertEqual(current.total, 19)
        self.assertEqual(current.lines[1].price_origin, 'source_default')

    def test_explicit_fallback(self):
        first, second = self.external_pair()
        install(self.warehouse, first)
        decide(self.warehouse, 'jia', action='confirm', price=9)
        install(self.warehouse, second)
        self.assertEqual(preview(self.warehouse).lines[0].unit_price, 9)
        decide(self.warehouse, 'jia', action='withdraw')
        explicit = preview(self.warehouse).lines[0]
        self.assertEqual((explicit.unit_price, explicit.price_origin), (5, 'source_explicit'))
        decide(self.warehouse, 'jia', action='withdraw')
        self.assertEqual(preview(self.warehouse).lines[0], explicit)
