from dataclasses import replace

from claims.receipt import SplitRequest
from claims.split import split
from delivery.history import read_batch_delivery
from delivery.publish import publish
from delivery.receipts import get_page
from pages.request import PageRequest
from reconcile.totals import GroupTotals
from tests.support import Interrupted, Workday, WorkdayCase, interrupt, row_details


class DeliveryTests(WorkdayCase):
    def _assert_handoff(self, batch_id, parent_receipt, successor_receipt):
        self.assertIsNotNone(parent_receipt)
        self.assertIsNotNone(successor_receipt)
        signed = parent_receipt.rows + successor_receipt.rows
        positions = [row.position for row in signed]
        litres = sum(row.litres for row in signed if row.litres is not None)
        self.assertEqual(len(set(positions)), len(positions), f'DUPLICATE_DELIVERY positions={positions} litres={litres}')
        self.assertEqual(row_details(parent_receipt.rows), [(0, 7, 'day', 101)])
        self.assertEqual(row_details(successor_receipt.rows), [(1, 11, 'night', 102), (2, 13, 'night', 103)])
        self.assertNotEqual(parent_receipt.claim_id, successor_receipt.claim_id)
        report = self.work.audit(batch_id)
        self.assertEqual(report.delivered, signed)
        self.assertEqual(report.undelivered_positions, ())
        self.assertEqual(report.groups, (('day', GroupTotals(1, 0, 7)), ('night', GroupTotals(2, 0, 24))))
        self.assertEqual(report.total, GroupTotals(3, 0, 31))
        self.assertEqual([row.source.station for row in signed], ['松桥'] * 3)
        self.assertEqual([row.source.document for row in signed], ['station-day'] * 3)

    def _late_parent(self):
        batch_id, original = self.seed()
        parent_page = self.work.candidate(original, 'parent', 0, 3)
        request = SplitRequest('transfer', original.claim_id, 1, 'night')
        result = split(self.work.claims, self.work.deliveries, request)
        successor_page = self.work.candidate(result.successor, 'tail', 1, 3)
        successor_receipt = publish(self.work.candidates, self.work.deliveries, successor_page)
        parent_receipt = publish(self.work.candidates, self.work.deliveries, parent_page)
        return batch_id, parent_page, parent_receipt, successor_receipt

    def test_late_parent_page(self):
        batch_id, _, parent_receipt, successor_receipt = self._late_parent()
        self._assert_handoff(batch_id, parent_receipt, successor_receipt)

    def test_split_wins(self):
        batch_id, original = self.seed()
        page = self.work.candidate(original, 'parent', 0, 3)
        other = Workday(self.root)
        signed = []

        def transfer_first():
            self.assertEqual(read_batch_delivery(other.deliveries, batch_id), ())
            request = SplitRequest('transfer', original.claim_id, 1, 'night')
            result = split(other.claims, other.deliveries, request)
            successor = other.candidate(result.successor, 'tail', 1, 3)
            signed.append(publish(other.candidates, other.deliveries, successor))

        parent = publish(self.work.candidates, self.work.deliveries, page, before_decision=transfer_first)
        self.assertEqual(len(signed), 1)
        self._assert_handoff(batch_id, parent, signed[0])

    def test_late_parent_receipt(self):
        batch_id, candidate, parent, successor = self._late_parent()
        self.assertEqual(candidate.positions, (0, 1, 2))
        self.reopen()
        self.assertEqual(self.work.candidates.get_candidate('parent'), candidate)
        self.assertEqual(get_page(self.work.deliveries, 'page:parent'), parent)
        self.assertEqual(row_details(get_page(self.work.deliveries, 'page:parent').rows), [(0, 7, 'day', 101)])
        self.assertEqual(get_page(self.work.deliveries, 'page:tail'), successor)
        self.assertEqual(len(read_batch_delivery(self.work.deliveries, batch_id)), 3)

    def test_empty_tail_page(self):
        batch_id, original = self.seed()
        old_tail = self.work.candidate(original, 'old-tail', 1, 3)
        request = SplitRequest('transfer', original.claim_id, 1, 'night')
        result = split(self.work.claims, self.work.deliveries, request)
        self.assertIsNone(publish(self.work.candidates, self.work.deliveries, old_tail))
        self.assertIsNone(get_page(self.work.deliveries, 'page:old-tail'))
        self.assertEqual(read_batch_delivery(self.work.deliveries, batch_id), ())
        new_tail = self.work.candidate(result.successor, 'new-tail', 1, 3)
        receipt = publish(self.work.candidates, self.work.deliveries, new_tail)
        self.reopen()
        self.assertIsNone(publish(self.work.candidates, self.work.deliveries, old_tail, after_commit=interrupt))
        self.assertEqual(read_batch_delivery(self.work.deliveries, batch_id), receipt.rows)

    def test_distinct_request(self):
        batch_id, original = self.seed()
        first = self.work.candidate(original, 'first', 0, 3)
        second = self.work.candidate(original, 'second', 0, 3)
        receipt = publish(self.work.candidates, self.work.deliveries, first)
        self.assertIsNone(publish(self.work.candidates, self.work.deliveries, second))
        self.assertIsNone(get_page(self.work.deliveries, 'page:second'))
        self.assertEqual(get_page(self.work.deliveries, 'page:first'), receipt)
        self.assertEqual(read_batch_delivery(self.work.deliveries, batch_id), receipt.rows)

    def test_partial_overlap_with_signed_page(self):
        batch_id, original = self.seed()
        first = self.work.candidate(original, 'first', 0, 2)
        overlap = self.work.candidate(original, 'overlap', 1, 3)
        publish(self.work.candidates, self.work.deliveries, first)
        receipt = publish(self.work.candidates, self.work.deliveries, overlap)
        self.assertEqual(row_details(receipt.rows), [(2, 13, 'day', 103)])
        self.assertEqual(self.work.audit(batch_id).total, GroupTotals(3, 0, 31))

    def test_full_transfer(self):
        batch_id, original = self.seed()
        old = self.work.candidate(original, 'old', 0, 3)
        result = split(self.work.claims, self.work.deliveries, SplitRequest('whole', original.claim_id, 0, 'night'))
        self.assertEqual((result.parent.span.start, result.parent.span.stop), (0, 0))
        self.assertIsNone(publish(self.work.candidates, self.work.deliveries, old))
        page = self.work.candidate(result.successor, 'new', 0, 3)
        publish(self.work.candidates, self.work.deliveries, page)
        self.assertEqual(self.work.audit(batch_id).groups, (('night', GroupTotals(3, 0, 31)),))

    def test_reopen_after_lost_reply(self):
        batch_id, original = self.seed()
        parent_page = self.work.candidate(original, 'parent', 0, 3)
        request = SplitRequest('transfer', original.claim_id, 1, 'night')
        with self.assertRaises(Interrupted):
            split(self.work.claims, self.work.deliveries, request, after_commit=interrupt)
        self.reopen()
        moved = split(self.work.claims, self.work.deliveries, request)
        with self.assertRaises(ValueError):
            split(self.work.claims, self.work.deliveries, replace(request, successor_group='other'))
        tail = self.work.candidate(moved.successor, 'tail', 1, 3)
        successor = publish(self.work.candidates, self.work.deliveries, tail)
        with self.assertRaises(Interrupted):
            publish(self.work.candidates, self.work.deliveries, parent_page, after_commit=interrupt)
        self.reopen()
        parent = publish(self.work.candidates, self.work.deliveries, parent_page)
        incompatible = replace(parent_page, request=PageRequest('parent', original.claim_id, 0, 1), positions=(0,))
        with self.assertRaises(ValueError):
            publish(self.work.candidates, self.work.deliveries, incompatible)
        self.assertEqual(get_page(self.work.deliveries, 'page:parent'), parent)
        self._assert_handoff(batch_id, parent, successor)

    def test_publish_replay(self):
        batch_id, original = self.seed()
        page = self.work.candidate(original, 'whole', 0, 3)
        with self.assertRaises(Interrupted):
            publish(self.work.candidates, self.work.deliveries, page, after_commit=interrupt)
        self.reopen()
        stored = get_page(self.work.deliveries, 'page:whole')
        self.assertIsNotNone(stored)
        self.assertEqual(publish(self.work.candidates, self.work.deliveries, page, after_commit=interrupt), stored)
        with self.assertRaises(ValueError):
            publish(self.work.candidates, self.work.deliveries, replace(page, positions=(0, 2, 1)))
        self.assertEqual(row_details(stored.rows), [(0, 7, 'day', 101), (1, 11, 'day', 102), (2, 13, 'day', 103)])
        self.assertEqual(self.work.audit(batch_id).total, GroupTotals(3, 0, 31))

    def test_unknown_page(self):
        _, original = self.seed()
        self.work.candidate(original, 'waiting', 0, 3)
        self.assertIsNone(get_page(self.work.deliveries, 'page:waiting'))
        self.assertIsNone(get_page(self.work.deliveries, 'page:unknown'))

    def test_repeat_init(self):
        batch_id, original = self.seed()
        parent = self.work.candidate(original, 'parent', 0, 3)
        request = SplitRequest('transfer', original.claim_id, 1, 'night')
        moved = split(self.work.claims, self.work.deliveries, request)
        receipt = publish(self.work.candidates, self.work.deliveries, parent)
        before = self.work.audit(batch_id)
        self.reopen().initialize()
        self.assertEqual(self.work.candidates.get_candidate('parent'), parent)
        self.assertEqual(split(self.work.claims, self.work.deliveries, request), moved)
        self.assertEqual(self.work.claims.list_claims(batch_id), (moved.parent, moved.successor))
        self.assertEqual(get_page(self.work.deliveries, 'page:parent'), receipt)
        self.assertEqual(self.work.audit(batch_id), before)
        self.assertEqual(before.total, GroupTotals(1, 0, 7))
        self.assertEqual(before.undelivered_positions, (1, 2))

    def test_failed_publish_then_retry(self):
        batch_id, original = self.seed()
        page = self.work.candidate(original, 'interrupted', 0, 3)
        observer = Workday(self.root)

        def fail_before_commit():
            self.assertIsNone(get_page(observer.deliveries, 'page:interrupted'))
            self.assertEqual(read_batch_delivery(observer.deliveries, batch_id), ())
            interrupt()

        with self.assertRaises(Interrupted):
            publish(self.work.candidates, self.work.deliveries, page, before_commit=fail_before_commit)
        self.reopen()
        self.assertIsNone(get_page(self.work.deliveries, 'page:interrupted'))
        self.assertEqual(read_batch_delivery(self.work.deliveries, batch_id), ())
        self.assertEqual(self.work.candidates.get_candidate('interrupted'), page)
        receipt = publish(self.work.candidates, self.work.deliveries, page)
        self.assertEqual(get_page(self.work.deliveries, 'page:interrupted'), receipt)
        self.assertEqual(publish(self.work.candidates, self.work.deliveries, page), receipt)
        self.assertEqual(row_details(read_batch_delivery(self.work.deliveries, batch_id)), [(0, 7, 'day', 101), (1, 11, 'day', 102), (2, 13, 'day', 103)])
