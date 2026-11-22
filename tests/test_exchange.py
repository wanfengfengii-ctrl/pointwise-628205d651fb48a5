import json

from lake.exchange.issue import issue
from lake.exchange.receive import receive_bundle
from lake.install.catalog import install
from lake.install.history import read_installation
from lake.settle.publish import preview
from lake.source.revisions import freeze
from lake.source.store import SourceStore
from tests import LakeCase, ROWS


class ExchangeTests(LakeCase):
    def test_detached_install(self):
        with SourceStore(self.source_path) as source:
            first = freeze(source, 'day', None, 5, ROWS)
            sealed = issue(source, first)
        self.source_path.unlink()
        self.assertEqual(install(self.warehouse, sealed), first)
        current = preview(self.warehouse)
        self.assertEqual([line.original_id for line in current.lines], ['jia', 'yi', 'bing'])
        self.assertEqual([line.amount for line in current.lines], [5, 5, 5])
        self.assertEqual([(total.station, total.amount) for total in current.stations], [('east', 10), ('west', 5)])
        self.assertEqual(current.total, 15)
        with self.warehouse.read_transaction() as connection:
            history = read_installation(connection, first)
        self.assertEqual((history.issue_id, history.predecessor, history.ordinal),
                         (receive_bundle(sealed).issue_id, None, 1))

    def test_missing_row(self):
        first, second = self.issued_pair()
        install(self.warehouse, first)
        before = preview(self.warehouse)
        raw = json.loads(second)
        raw['rows'].pop()
        with self.assertRaisesRegex(ValueError, 'coverage mismatch'):
            install(self.warehouse, json.dumps(raw))
        self.assertEqual(preview(self.warehouse), before)
        with self.warehouse.read_transaction() as connection:
            self.assertIsNone(read_installation(connection, raw['revision_id']))

    def test_changed_content(self):
        first, second = self.issued_pair()
        install(self.warehouse, first)
        previous = self.active_base()
        raw = json.loads(second)
        raw['rows'][0]['quantity'] = 4
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            install(self.warehouse, json.dumps(raw))
        self.assertEqual(self.active_base(), previous)

    def test_required_evidence_and_price_declaration(self):
        first, _ = self.external_pair()
        without_evidence = json.loads(first)
        without_evidence['evidence'] = {'other': {}}
        invalid_price = json.loads(first)
        invalid_price['rows'][0]['source_price'] = None
        duplicated = json.loads(first)
        duplicated['rows'].append(duplicated['rows'][0])
        for raw, reason in ((without_evidence, 'missing frozen_v1'),
                            (invalid_price, 'inconsistent price declaration'),
                            (duplicated, 'duplicate bundle original_id')):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                install(self.warehouse, json.dumps(raw))
        self.assertIsNone(self.active_base())

    def test_other_named_evidence_can_accompany_v1(self):
        first, _ = self.external_pair()
        raw = json.loads(first)
        raw['evidence']['dispatch_note'] = {'desk': 'east'}
        self.assertEqual(install(self.warehouse, json.dumps(raw)), 'outside-r1')
        self.assertEqual(preview(self.warehouse).total, 15)

    def test_incomplete_frozen_rows_cannot_be_issued(self):
        with SourceStore(self.source_path) as source:
            revision = freeze(source, 'day', None, 5, ROWS)
            with source.write_transaction() as connection:
                connection.execute('DELETE FROM source_rows WHERE revision_id = ? AND position = 1', (revision,))
            with self.assertRaisesRegex(ValueError, 'incomplete frozen rows'):
                issue(source, revision)
