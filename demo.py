import json
import tempfile
from pathlib import Path

from lake.exchange.issue import issue
from lake.install.catalog import install
from lake.install.repository import WarehouseStore
from lake.review.decisions import decide
from lake.settle.publish import preview, publish
from lake.settle.receipt import read
from lake.source.revisions import freeze
from lake.source.store import SourceStore


def _amounts(snapshot):
    return {
        'rows': [line.amount for line in snapshot.lines],
        'stations': {entry.station: entry.amount for entry in snapshot.stations},
        'total': snapshot.total,
    }


def main() -> None:
    sample = Path(__file__).resolve().parent / 'samples' / 'day.json'
    day = json.loads(sample.read_text(encoding='utf-8'))
    confirmation = day['confirmation']
    with tempfile.TemporaryDirectory() as folder:
        source_path = Path(folder) / 'source.sqlite'
        warehouse_path = Path(folder) / 'warehouse.sqlite'
        with SourceStore(source_path) as source:
            r1 = freeze(source, day['stream'], None, day['default_r1'], day['rows'])
            first = issue(source, r1)
        with WarehouseStore(warehouse_path) as warehouse:
            if install(warehouse, first) != r1:
                raise AssertionError('first installation did not return its frozen revision')
            initial = _amounts(preview(warehouse))
            old_id = publish(warehouse)
            decide(warehouse, confirmation['original_id'], action='confirm', price=confirmation['price'])
            with SourceStore(source_path) as source:
                r2 = freeze(source, day['stream'], r1, day['default_r2'], day['rows'])
                second = issue(source, r2)
            if install(warehouse, second) != r2:
                raise AssertionError('successor installation did not return its frozen revision')
            rebased = _amounts(preview(warehouse))
            if rebased['rows'] != [5, 5, 7] or rebased['total'] != 17:
                raise AssertionError(f'PRICE_ORIGIN_DRIFT actual={rebased}')
            new_id = publish(warehouse)
            decide(warehouse, confirmation['original_id'], action='withdraw')
        with WarehouseStore(warehouse_path) as warehouse:
            current = preview(warehouse)
            original, revised = read(warehouse, old_id), read(warehouse, new_id)
            if (current.revision_id, original.revision_id, revised.revision_id) != (r2, r1, r2):
                raise AssertionError('reopened ledger or receipt has the wrong source revision')
            actual = {'initial': initial, 'rebased': rebased, 'withdrawn': _amounts(current)}
            downstream_actual = {'first_receipt': _amounts(original), 'second_receipt': _amounts(revised)}

    expected = {
        'initial': {'rows': [5, 5, 5], 'stations': {'east': 10, 'west': 5}, 'total': 15},
        'rebased': {'rows': [5, 5, 7], 'stations': {'east': 10, 'west': 7}, 'total': 17},
        'withdrawn': {'rows': [5, 7, 7], 'stations': {'east': 12, 'west': 7}, 'total': 19},
    }
    downstream_expected = {'first_receipt': expected['initial'], 'second_receipt': expected['rebased']}
    if actual != expected or downstream_actual != downstream_expected:
        raise AssertionError(f'ledger reconciliation failed: {actual}, {downstream_actual}')
    scenario = {
        'case_id': 'V7.history_after_withdrawal',
        'input': day,
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': ['lake/source/revisions.py', 'lake/exchange/issue.py', 'lake/install/catalog.py',
                       'lake/review/decisions.py', 'lake/review/pricing.py', 'lake/settle/lines.py',
                       'lake/settle/totals.py', 'lake/settle/publish.py', 'lake/settle/receipt.py'],
        'oracle': 'Unit quantities give the selected prices as row amounts. East adds jia and yi. '
                  'West takes bing. The two reopened receipts match the hand totals before withdrawal.',
    }
    print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
