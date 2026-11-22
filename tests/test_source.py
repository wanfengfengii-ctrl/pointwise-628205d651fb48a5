from lake.exchange.issue import issue
from lake.exchange.receive import receive_bundle
from lake.source.revisions import freeze, read_frozen_revision
from lake.source.rows import SourceRow
from lake.source.store import SourceStore
from lake.source.streams import read_stream_head
from tests import LakeCase, ROWS


class SourceTests(LakeCase):
    def test_duplicate_original_id(self):
        with SourceStore(self.source_path) as source:
            first = freeze(source, 'day', None, 5, ROWS)
            with self.assertRaisesRegex(ValueError, 'duplicate original_id'):
                freeze(source, 'day', first, 7, (*ROWS, SourceRow('jia', 'west', 9)))
            self.assertEqual(read_stream_head(source, 'day').revision_id, first)
            self.assertEqual(read_frozen_revision(source, first).rows, ROWS)

    def test_stale_predecessor(self):
        with SourceStore(self.source_path) as source:
            first = freeze(source, 'day', None, 5, ROWS)
            second = freeze(source, 'day', first, 7, ROWS)
            with self.assertRaisesRegex(ValueError, 'current stream head'):
                freeze(source, 'day', first, 8, ROWS)
            with self.assertRaisesRegex(ValueError, 'empty predecessor'):
                freeze(source, 'another-day', second, 8, ROWS)
            self.assertEqual(read_stream_head(source, 'day').revision_id, second)
            self.assertIsNone(read_stream_head(source, 'another-day'))
            self.assertEqual(read_frozen_revision(source, first).default_price, 5)
            self.assertEqual(read_frozen_revision(source, second).predecessor, first)

    def test_source_reopen(self):
        with SourceStore(self.source_path) as source:
            first = freeze(source, 'day', None, 5, ROWS)
            package = issue(source, first)
            second = freeze(source, 'day', first, 7, ROWS)
        with SourceStore(self.source_path) as reopened:
            reopened.initialize()
            self.assertEqual(issue(reopened, first), package)
            self.assertEqual(read_stream_head(reopened, 'day').revision_id, second)
            self.assertEqual(receive_bundle(issue(reopened, second)).default_price, 7)
            self.assertEqual([(row.price_kind, row.source_price) for row in receive_bundle(package).rows],
                             [('explicit', 5), ('default', None), ('default', None)])

    def test_invalid_initial_rows_and_prices(self):
        with SourceStore(self.source_path) as source:
            for value, rows in (
                (None, ROWS), (True, ROWS), (5.0, ROWS),
                (5, [{'original_id': 'jia', 'quantity': 1}]),
                (5, [SourceRow('', 'east', 1)]), (5, [SourceRow('jia', 'east', True)]),
                (5, [SourceRow('jia', 'east', 1, 5.0)]),
            ):
                with self.subTest(default=value, rows=rows), self.assertRaises(ValueError):
                    freeze(source, 'day', None, value, rows)
            self.assertIsNone(read_stream_head(source, 'day'))
            with self.assertRaisesRegex(KeyError, 'unknown revision'):
                issue(source, 'missing')

    def test_source_failed_commit_keeps_head(self):
        with SourceStore(self.source_path) as source:
            first = freeze(source, 'day', None, 5, ROWS)
            self.deny_commit_on_insert(source, 'source_revisions')
            self.assert_commit_refused(source, freeze, 'day', first, 7, ROWS)
        with SourceStore(self.source_path) as source:
            self.assertEqual(read_stream_head(source, 'day').revision_id, first)
            self.assertEqual(read_frozen_revision(source, first).rows, ROWS)
            self.assertEqual(source.connection.execute('SELECT count(*) FROM source_revisions').fetchone()[0], 1)
