import json
import sys
import unittest

import lake.settle.publish as settlement
from check_project import main as check_v1
from lake.exchange.issue import issue
from lake.install.catalog import install
from lake.install.repository import WarehouseStore
from lake.review.decisions import decide
from lake.settle.receipt import read
from lake.source.revisions import freeze
from lake.source.rows import SourceRow
from lake.source.store import SourceStore
from tests import LakeCase


ROWS = (SourceRow("jia", "east", 1), SourceRow("yi", "west", 1, 5))
PENDING = {"state": "pending", "cause": None, "receipt_id": None}


def editions(path, *specs):
    result = []
    predecessor = None
    with SourceStore(path) as source:
        for price, rows in specs:
            predecessor = freeze(source, "station-day", predecessor, price, rows)
            result.append((predecessor, issue(source, predecessor)))
    return result


def v1_sample():
    books = editions(":memory:", (5, ROWS), (7, ROWS), (5, ROWS))
    observed = []
    with WarehouseStore(":memory:") as warehouse:
        for revision, data in books:
            if install(warehouse, data) != revision:
                raise AssertionError("the installation returned the wrong revision")
            observed.append([line.unit_price for line in settlement.preview(warehouse).lines])
        receipt = read(warehouse, settlement.publish(warehouse))
    if observed != [[5, 5], [7, 5], [5, 5]] or receipt.total != 10:
        raise AssertionError(f"unexpected V1 ledger: {observed}, total={receipt.total}")
    print(json.dumps({"v1_prices": observed, "v1_total": receipt.total}))


class StationSignoffTests(LakeCase):
    show_demo = False

    def assert_invalid(self, ticket, cause):
        self.assertEqual(settlement.status(self.warehouse, ticket), {
            "state": "invalidated", "cause": cause, "receipt_id": None,
        })
        with self.assertRaises(ValueError):
            settlement.sign(self.warehouse, ticket)

    def test_install_excursion_and_unaffected_station(self):
        first, second, third = editions(self.source_path, (5, ROWS), (7, ROWS), (5, ROWS))
        install(self.warehouse, first[1])
        east = settlement.stage(self.warehouse, "east-ticket", "east")
        west = settlement.stage(self.warehouse, "west-ticket", "west")
        self.assertEqual(east, (("jia", 1, 5),))
        self.assertEqual(west, (("yi", 1, 5),))
        install(self.warehouse, second[1])
        install(self.warehouse, third[1])
        self.reopen_warehouse()
        cause = {"kind": "install", "revision_id": second[0]}
        self.assert_invalid("east-ticket", cause)
        self.assertEqual(settlement.stage(self.warehouse, "east-ticket", "east"), east)
        with self.assertRaises(ValueError):
            settlement.stage(self.warehouse, "east-ticket", "west")
        self.assertEqual(settlement.status(self.warehouse, "west-ticket"), PENDING)
        receipt_id = settlement.sign(self.warehouse, "west-ticket")
        saved = read(self.warehouse, receipt_id)
        self.assertEqual(saved.revision_id, third[0])
        self.assertEqual([(line.original_id, line.amount) for line in saved.lines], [("yi", 5)])
        self.assertEqual([(total.station, total.amount) for total in saved.stations], [("west", 5)])
        decide(self.warehouse, "yi", action="confirm", price=9)
        self.reopen_warehouse()
        signed = settlement.status(self.warehouse, "west-ticket")
        self.assertEqual(signed, {"state": "signed", "cause": None, "receipt_id": receipt_id})
        self.assertEqual(settlement.sign(self.warehouse, "west-ticket"), receipt_id)
        self.assertEqual(read(self.warehouse, receipt_id), saved)
        if self.show_demo:
            print(json.dumps({"east": settlement.status(self.warehouse, "east-ticket"),
                              "west": signed, "west_frozen_total": saved.total}, sort_keys=True))

    def test_review_excursion_and_equal_price_basis(self):
        (first,) = editions(self.source_path, (5, ROWS))
        install(self.warehouse, first[1])
        settlement.stage(self.warehouse, "old", "east")
        change = decide(self.warehouse, "jia", action="confirm", price=7)
        decide(self.warehouse, "jia", action="withdraw")
        self.reopen_warehouse()
        self.assert_invalid("old", {"kind": "review", "sequence": change.sequence})
        settlement.stage(self.warehouse, "new", "east")
        same = decide(self.warehouse, "jia", action="confirm", price=5)
        self.assertEqual(settlement.status(self.warehouse, "new"), PENDING)
        line, = read(self.warehouse, settlement.sign(self.warehouse, "new")).lines
        self.assertEqual((line.unit_price, line.price_origin, line.decision_sequence),
                         (5, "confirmation", same.sequence))

    def test_same_price_confirmation_masks_install_until_withdrawal(self):
        first, second = editions(self.source_path, (5, ROWS), (7, ROWS))
        install(self.warehouse, first[1])
        settlement.stage(self.warehouse, "masked", "east")
        decide(self.warehouse, "jia", action="confirm", price=5)
        install(self.warehouse, second[1])
        self.assertEqual(settlement.status(self.warehouse, "masked"), PENDING)
        gone = decide(self.warehouse, "jia", action="withdraw")
        self.assert_invalid("masked", {"kind": "review", "sequence": gone.sequence})

    def test_equal_total_and_only_order_changes(self):
        a, west = ROWS
        b = SourceRow("bing", "east", 1)
        cheaper = SourceRow(a.original_id, a.station, a.quantity, 4)
        dearer = SourceRow(b.original_id, b.station, b.quantity, 6)
        first, second, third = editions(self.source_path, (5, (a, b, west)),
                                       (5, (cheaper, dearer, west)), (5, (dearer, cheaper, west)))
        install(self.warehouse, first[1])
        settlement.stage(self.warehouse, "equal-total", "east")
        install(self.warehouse, second[1])
        self.assert_invalid("equal-total", {"kind": "install", "revision_id": second[0]})
        settlement.stage(self.warehouse, "order-only", "east")
        install(self.warehouse, third[1])
        self.assert_invalid("order-only", {"kind": "install", "revision_id": third[0]})

    def test_failed_install_keeps_pending(self):
        first, second = editions(self.source_path, (5, ROWS), (7, ROWS))
        install(self.warehouse, first[1])
        settlement.stage(self.warehouse, "keep", "east")
        self.deny_commit_on_insert(self.warehouse, "installation_history")
        self.assert_commit_refused(self.warehouse, install, second[1])
        self.reopen_warehouse()
        self.assertEqual(settlement.status(self.warehouse, "keep"), PENDING)
        self.assertEqual(settlement.preview(self.warehouse).revision_id, first[0])

    def test_failed_review_keeps_pending(self):
        (first,) = editions(self.source_path, (5, ROWS))
        install(self.warehouse, first[1])
        settlement.stage(self.warehouse, "keep", "east")
        self.deny_commit_on_insert(self.warehouse, "review_journal")
        self.assert_commit_refused(self.warehouse, decide, "jia", action="confirm", price=7)
        self.reopen_warehouse()
        self.assertEqual(settlement.status(self.warehouse, "keep"), PENDING)
        self.assertEqual(settlement.preview(self.warehouse).lines[0].unit_price, 5)

    def test_failed_sign_can_retry(self):
        (first,) = editions(self.source_path, (5, ROWS))
        install(self.warehouse, first[1])
        settlement.stage(self.warehouse, "retry", "east")
        self.deny_commit_on_insert(self.warehouse, "receipts")
        self.assert_commit_refused(self.warehouse, settlement.sign, "retry")
        self.reopen_warehouse()
        self.assertEqual(settlement.status(self.warehouse, "retry"), PENDING)
        self.assertEqual(self.receipt_ids(), set())
        self.allow_commits(self.warehouse)
        receipt_id = settlement.sign(self.warehouse, "retry")
        self.assertEqual(read(self.warehouse, receipt_id).total, 5)


def main(args):
    if args == ["baseline"]:
        v1_sample()
        return 0
    if args == ["verify"]:
        if result := check_v1():
            return result
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(StationSignoffTests)
    elif args == ["demo"]:
        StationSignoffTests.show_demo = True
        suite = unittest.TestSuite([
            StationSignoffTests("test_install_excursion_and_unaffected_station"),
        ])
    else:
        print("usage: python3 -B verify_station_signoff.py baseline|verify|demo", file=sys.stderr)
        return 2
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
