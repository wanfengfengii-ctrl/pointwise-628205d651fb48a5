import json

from lake.exchange.issue import issue
from lake.install.catalog import install
from lake.install.history import read_installation
from lake.review.decisions import decide
from lake.settle.publish import preview
from lake.source.revisions import freeze
from lake.source.store import SourceStore
from tests import LakeCase, ROWS


class InstallTests(LakeCase):
    def test_failed_rebase(self):
        first, second = self.issued_pair()
        original = install(self.warehouse, first)
        confirmation = decide(self.warehouse, 'yi', action='confirm', price=6)
        before = preview(self.warehouse)
        self.deny_commit_on_insert(self.warehouse, 'installation_history')
        self.assert_commit_refused(self.warehouse, install, second)
        self.reopen_warehouse()
        self.assertEqual(self.active_base().revision_id, original)
        self.assertEqual(preview(self.warehouse), before)
        self.assertEqual(preview(self.warehouse).lines[1].decision_sequence, confirmation.sequence)
        with self.warehouse.read_transaction() as connection:
            self.assertIsNone(read_installation(connection, json.loads(second)['revision_id']))
            self.assertIsNotNone(read_installation(connection, original))

    def test_retry_after_failed_install(self):
        first, second = self.external_pair()
        install(self.warehouse, first)
        decision = decide(self.warehouse, 'yi', action='confirm', price=5)
        self.deny_commit_on_insert(self.warehouse, 'installation_history')
        self.assert_commit_refused(self.warehouse, install, second)
        self.reopen_warehouse()
        self.assertEqual(self.active_base().revision_id, 'outside-r1')
        self.allow_commits(self.warehouse)
        self.assertEqual(install(self.warehouse, second), 'outside-r2')
        self.reopen_warehouse()
        with self.warehouse.read_transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM installation_history').fetchone()[0], 2)
            history = read_installation(connection, 'outside-r2')
        self.assertEqual((history.predecessor, history.ordinal, history.issue_id),
                         ('outside-r1', 2, 'external-002'))
        current = preview(self.warehouse)
        self.assertEqual([line.amount for line in current.lines], [5, 5, 7])
        self.assertEqual(current.lines[1].decision_sequence, decision.sequence)
        with self.assertRaisesRegex(ValueError, 'direct successor'):
            install(self.warehouse, second)
        self.assertEqual(preview(self.warehouse), current)

    def test_wrong_lineage(self):
        with SourceStore(self.source_path) as source:
            r1 = freeze(source, 'day', None, 5, ROWS)
            r2 = freeze(source, 'day', r1, 7, ROWS)
            r3 = freeze(source, 'day', r2, 9, ROWS)
            foreign = freeze(source, 'other', None, 5, ROWS)
            first, third, other = (issue(source, revision) for revision in (r1, r3, foreign))
        install(self.warehouse, first)
        decide(self.warehouse, 'yi', action='confirm', price=6)
        before = preview(self.warehouse)
        for data, reason in ((other, 'another stream'), (third, 'direct successor')):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                install(self.warehouse, data)
        self.assertEqual(preview(self.warehouse), before)
        with self.warehouse.read_transaction() as connection:
            self.assertIsNone(read_installation(connection, foreign))
            self.assertIsNone(read_installation(connection, r3))

    def test_empty_warehouse_requires_first_revision(self):
        first, second = self.external_pair()
        with self.assertRaisesRegex(ValueError, 'first stream revision'):
            install(self.warehouse, second)
        self.assertIsNone(self.active_base())
        self.assertEqual(install(self.warehouse, first), 'outside-r1')
