from dataclasses import replace

from claims.ranges import ClaimRange
from claims.receipt import SplitRequest
from claims.split import split
from delivery.history import read_batch_delivery
from delivery.publish import publish
from delivery.receipts import get_page
from pages.build import prepare
from pages.request import PageRequest
from tests.support import Interrupted, Workday, WorkdayCase, interrupt, row_details


class SplitTests(WorkdayCase):
    def test_prepared_page_crosses_split(self):
        batch_id, original = self.seed()
        parent_page = self.work.candidate(original, 'parent', 0, 3)
        receipt = split(self.work.claims, self.work.deliveries, SplitRequest('transfer', original.claim_id, 1, 'night'))
        self.assertEqual(receipt.parent.span, ClaimRange(0, 1))
        self.assertEqual(receipt.successor.span, ClaimRange(1, 3))
        self.assertEqual(receipt.successor.batch_id, batch_id)
        self.assertEqual(self.work.claims.list_claims(batch_id), (receipt.parent, receipt.successor))
        self.assertEqual(self.work.candidate(receipt.successor, 'tail', 1, 3).positions, (1, 2))
        self.assertEqual(prepare(self.work.candidates, parent_page.request), parent_page)
        self.assertIsNone(get_page(self.work.deliveries, 'page:parent'))
        self.assertEqual(read_batch_delivery(self.work.deliveries, batch_id), ())

    def test_request_identity(self):
        _, original = self.seed()
        page = self.work.candidate(original, 'stable', 0, 2)
        self.assertEqual(self.work.candidate(original, 'stable', 0, 2), page)
        with self.assertRaisesRegex(ValueError, 'bound'):
            self.work.candidate(original, 'stable', 1, 3)
        self.assertEqual(self.work.candidates.get_candidate('stable'), page)
        self.assertEqual(page.positions, (0, 1))

    def test_prepare_bounds(self):
        _, original = self.seed()
        result = split(self.work.claims, self.work.deliveries, SplitRequest('transfer', original.claim_id, 1, 'night'))
        for claim, start, stop in ((result.parent, 0, 2), (result.successor, 0, 2), (result.successor, 2, 4)):
            with self.subTest(claim=claim.claim_id, start=start, stop=stop):
                with self.assertRaises(ValueError):
                    prepare(self.work.candidates, PageRequest('outside', claim.claim_id, start, stop))
                self.assertIsNone(self.work.candidates.get_candidate('outside'))
                self.assertIsNone(get_page(self.work.deliveries, 'page:outside'))

    def test_illegal_boundary(self):
        batch_id, original = self.seed()
        for boundary in (-1, 3, 50, True):
            with self.subTest(boundary=boundary):
                with self.assertRaises(ValueError):
                    split(self.work.claims, self.work.deliveries, SplitRequest('outside', original.claim_id, boundary, 'night'))
                self.assertEqual(self.work.claims.list_claims(batch_id), (original,))

    def test_tail_already_delivered(self):
        batch_id, original = self.seed()
        page = self.work.candidate(original, 'whole', 0, 3)
        receipt = publish(self.work.candidates, self.work.deliveries, page)
        with self.assertRaisesRegex(ValueError, 'tail already delivered'):
            split(self.work.claims, self.work.deliveries, SplitRequest('too-late', original.claim_id, 1, 'night'))
        self.assertEqual(self.work.claims.list_claims(batch_id), (original,))
        self.assertEqual(get_page(self.work.deliveries, receipt.receipt_id), receipt)
        self.assertEqual(row_details(receipt.rows), [(0, 7, 'day', 101), (1, 11, 'day', 102), (2, 13, 'day', 103)])

    def test_publish_wins(self):
        batch_id, original = self.seed()
        page = self.work.candidate(original, 'winner', 0, 3)
        other = Workday(self.root)
        published = []

        def sign_first():
            self.assertEqual(other.claims.list_claims(batch_id), (original,))
            published.append(publish(other.candidates, other.deliveries, page))

        request = SplitRequest('transfer', original.claim_id, 1, 'night')
        with self.assertRaisesRegex(ValueError, 'tail already delivered'):
            split(self.work.claims, self.work.deliveries, request, before_decision=sign_first)
        self.assertEqual(len(published), 1)
        self.assertEqual(self.work.claims.list_claims(batch_id), (original,))
        self.assertEqual(get_page(self.work.deliveries, 'page:winner'), published[0])
        report = self.work.audit(batch_id)
        self.assertEqual(report.total.litres, 31)
        self.assertEqual(tuple((group, total.litres) for group, total in report.groups), (('day', 31),))

    def test_published_prefix_does_not_block_tail(self):
        batch_id, original = self.seed()
        prefix = self.work.candidate(original, 'prefix', 0, 1)
        first = publish(self.work.candidates, self.work.deliveries, prefix)
        request = SplitRequest('transfer', original.claim_id, 1, 'night')
        result = split(self.work.claims, self.work.deliveries, request)
        page = self.work.candidate(result.successor, 'tail', 1, 3)
        publish(self.work.candidates, self.work.deliveries, page)
        self.assertEqual(get_page(self.work.deliveries, first.receipt_id), first)
        self.assertEqual(row_details(self.work.audit(batch_id).delivered), [(0, 7, 'day', 101), (1, 11, 'night', 102), (2, 13, 'night', 103)])

    def test_split_replay(self):
        batch_id, original = self.seed()
        request = SplitRequest('transfer', original.claim_id, 1, 'night')
        with self.assertRaises(Interrupted):
            split(self.work.claims, self.work.deliveries, request, after_commit=interrupt)
        self.reopen()
        parent, successor = self.work.claims.list_claims(batch_id)
        result = split(self.work.claims, self.work.deliveries, request, after_commit=interrupt)
        self.assertEqual((result.parent, result.successor), (parent, successor))
        self.assertEqual(result.successor.span, ClaimRange(1, 3))
        for changed in (replace(request, boundary=2), replace(request, successor_group='other')):
            with self.assertRaisesRegex(ValueError, 'bound'):
                split(self.work.claims, self.work.deliveries, changed)
        self.assertEqual(self.work.claims.list_claims(batch_id), (parent, successor))
