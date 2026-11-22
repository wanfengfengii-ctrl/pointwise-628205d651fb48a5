import sqlite3
import tempfile
import unittest
from pathlib import Path

from lake.exchange.issue import issue
from lake.install.catalog import load_active_base
from lake.install.repository import WarehouseStore
from lake.source.revisions import freeze
from lake.source.rows import SourceRow
from lake.source.store import SourceStore


SAMPLES = Path(__file__).resolve().parents[1] / 'samples'
ROWS = (SourceRow('jia', 'east', 1, 5), SourceRow('yi', 'east', 1), SourceRow('bing', 'west', 1))


class LakeCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.source_path = Path(folder.name) / 'source.sqlite'
        self.warehouse_path = Path(folder.name) / 'warehouse.sqlite'
        self.warehouse = WarehouseStore(self.warehouse_path)
        self.addCleanup(lambda: self.warehouse.close())

    def reopen_warehouse(self):
        self.warehouse.close()
        self.warehouse = WarehouseStore(self.warehouse_path)

    def issued_pair(self, rows=ROWS):
        with SourceStore(self.source_path) as source:
            r1 = freeze(source, 'day', None, 5, rows)
            first = issue(source, r1)
        with SourceStore(self.source_path) as source:
            r2 = freeze(source, 'day', r1, 7, rows)
            second = issue(source, r2)
        return first, second

    def external_pair(self):
        return tuple((SAMPLES / f'external-r{number}.json').read_bytes() for number in (1, 2))

    def active_base(self):
        with self.warehouse.read_transaction() as connection:
            return load_active_base(connection)

    def receipt_ids(self):
        with self.warehouse.read_transaction() as connection:
            return {row[0] for row in connection.execute('SELECT receipt_id FROM receipts')}

    def deny_commit_on_insert(self, store, table):
        allowed = {'source_revisions', 'installation_history', 'review_journal', 'receipts'}
        if table not in allowed:
            raise ValueError('unknown commit fixture table')
        with store.write_transaction() as connection:
            connection.execute('CREATE TABLE test_commit_parent (id INTEGER PRIMARY KEY)')
            connection.execute('''
                CREATE TABLE test_commit_child (
                    parent INTEGER REFERENCES test_commit_parent(id) DEFERRABLE INITIALLY DEFERRED
                )
            ''')
            connection.execute(f'''
                CREATE TRIGGER test_deny_commit AFTER INSERT ON {table}
                BEGIN
                    INSERT INTO test_commit_child (parent) VALUES (1);
                END
            ''')

    def allow_commits(self, store):
        with store.write_transaction() as connection:
            connection.execute('DROP TRIGGER test_deny_commit')

    def assert_commit_refused(self, store, operation, *args, **kwargs):
        statements = []
        store.connection.set_trace_callback(statements.append)
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
                operation(store, *args, **kwargs)
        finally:
            store.connection.set_trace_callback(None)
        self.assertIn('COMMIT', statements)
        self.assertFalse(store.connection.in_transaction)
        self.assertEqual(store.connection.execute('SELECT count(*) FROM test_commit_child').fetchone()[0], 0)
