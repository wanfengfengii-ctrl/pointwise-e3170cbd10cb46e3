import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from batches.freeze import freeze
from claims.assign import assign
from claims.receipt import SplitRequest
from claims.split import split
from delivery.handoff import HandoffReceipt, handoff, publish_offline
from delivery.history import read_batch_delivery
from delivery.publish import publish
from delivery.receipts import get_page
from offline_fixture import create_workday, detach_catalogue, open_workday, seed
from tests.support import Interrupted, interrupt, row_details, station_submission


class HandoffTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.work = create_workday(self.root)

    def _other_batch_page(self, request_id='other-page'):
        batch_id = freeze(self.work.batches, station_submission((3,), 'other-day'))
        claim = assign(self.work.claims, batch_id, 'day')
        return batch_id, self.work.candidate(claim, request_id, 0, 1)

    def test_coverage_rejection_keeps_id(self):
        fixture = seed(self.work)
        batch_id = fixture.batch_id
        for ids in (['wide'], ['spent'], ['wide', 'spent'], ['first'], ['wide', 'first', 'spent']):
            with self.subTest(ids=ids):
                with self.assertRaises(ValueError):
                    handoff(self.work.candidates, self.work.deliveries, 'shift', batch_id, ids)
        # A rejected validation does not consume the handoff id.
        receipt = handoff(self.work.candidates, self.work.deliveries, 'shift', batch_id, ['tail'])
        self.assertEqual(receipt, HandoffReceipt('shift', batch_id, ('tail',)))

    def test_failed_handoff_leaves_online_flow(self):
        fixture = seed(self.work, split_tail=False)
        with self.assertRaises(ValueError):
            # 'tail' does not exist yet, so the list names an unknown candidate.
            handoff(self.work.candidates, self.work.deliveries, 'shift', fixture.batch_id, ['wide', 'tail'])
        moved = split(self.work.claims, self.work.deliveries, fixture.split_request)
        tail = self.work.candidate(moved.successor, 'tail', 1, 3)
        receipt = publish(self.work.candidates, self.work.deliveries, tail)
        self.assertEqual(row_details(receipt.rows), [(1, None, 'night', 102), (2, 11, 'night', 103)])

    def test_invalid_arguments(self):
        fixture = seed(self.work)
        batch_id = fixture.batch_id
        other_batch, other_page = self._other_batch_page()
        bad_calls = [
            ('', batch_id, ['tail']),
            ('  ', batch_id, ['tail']),
            ('shift', '', ['tail']),
            ('shift', batch_id, 'tail'),
            ('shift', batch_id, b'tail'),
            ('shift', batch_id, []),
            ('shift', batch_id, ()),
            ('shift', batch_id, ['tail', 'tail']),
            ('shift', batch_id, ['tail', ' ']),
            ('shift', batch_id, ['tail', 7]),
            ('shift', 'batch:unknown', ['tail']),
            ('shift', batch_id, ['unknown']),
            ('shift', batch_id, ['tail', other_page.request.request_id]),
        ]
        for handoff_id, batch, ids in bad_calls:
            with self.subTest(handoff_id=handoff_id, batch_id=batch, request_ids=ids):
                with self.assertRaises(ValueError):
                    handoff(self.work.candidates, self.work.deliveries, handoff_id, batch, ids)
        # Nothing was transferred, so first-time online publishing still works.
        receipt = publish(self.work.candidates, self.work.deliveries, fixture.tail)
        self.assertEqual(row_details(receipt.rows), [(1, None, 'night', 102), (2, 11, 'night', 103)])
        self.assertIsNone(self.work.deliveries.get_batch_handoff(batch_id))
        self.assertIsNone(self.work.deliveries.get_batch_handoff(other_batch))

    def test_success_replay_and_rebind(self):
        fixture = seed(self.work)
        batch_id = fixture.batch_id
        calls = []
        receipt = handoff(
            self.work.candidates, self.work.deliveries, 'shift', batch_id, ['wide', 'tail'],
            after_checkpoint=lambda: calls.append('checkpoint'),
        )
        self.assertEqual(receipt, HandoffReceipt('shift', batch_id, ('tail', 'wide')))
        self.assertEqual(calls, ['checkpoint'])
        # Re-claiming with a reordered list returns the original receipt without callbacks.
        again = handoff(
            self.work.candidates, self.work.deliveries, 'shift', batch_id, ['tail', 'wide'],
            after_checkpoint=lambda: calls.append('again'),
        )
        self.assertEqual(again, receipt)
        self.assertEqual(calls, ['checkpoint'])
        with self.assertRaises(ValueError):
            handoff(self.work.candidates, self.work.deliveries, 'shift', batch_id, ['tail'])
        with self.assertRaises(ValueError):
            handoff(self.work.candidates, self.work.deliveries, 'shift', 'batch:other', ['tail', 'wide'])
        with self.assertRaises(ValueError):
            handoff(self.work.candidates, self.work.deliveries, 'other-shift', batch_id, ['tail'])

    def test_transfer_gates_online_first_time(self):
        fixture = seed(self.work, split_tail=False)
        batch_id = fixture.batch_id
        handoff(self.work.candidates, self.work.deliveries, 'shift', batch_id, ['wide'])
        with self.assertRaises(ValueError):
            split(self.work.claims, self.work.deliveries, fixture.split_request)
        with self.assertRaises(ValueError):
            publish(self.work.candidates, self.work.deliveries, fixture.wide)
        # Requests already processed are re-claimed as before.
        self.assertEqual(publish(self.work.candidates, self.work.deliveries, fixture.first), fixture.first_receipt)
        self.assertIsNone(publish(self.work.candidates, self.work.deliveries, fixture.spent))
        # Other batches keep the original flow.
        other_batch, other_page = self._other_batch_page()
        moved = split(self.work.claims, self.work.deliveries, SplitRequest('other-split', other_page.request.claim_id, 0, 'night'))
        night_page = self.work.candidate(moved.successor, 'other-night', 0, 1)
        receipt = publish(self.work.candidates, self.work.deliveries, night_page)
        self.assertEqual(row_details(receipt.rows), [(0, 3, 'night', 101)])
        self.assertEqual(self.work.audit(other_batch).total.litres, 3)

    def test_transfer_gates_after_split(self):
        fixture = seed(self.work)
        batch_id = fixture.batch_id
        handoff(self.work.candidates, self.work.deliveries, 'shift', batch_id, ['wide', 'tail'])
        with self.assertRaises(ValueError):
            publish(self.work.candidates, self.work.deliveries, fixture.wide)
        with self.assertRaises(ValueError):
            publish(self.work.candidates, self.work.deliveries, fixture.tail)
        with self.assertRaises(ValueError):
            split(self.work.claims, self.work.deliveries, SplitRequest('move-again', fixture.original.claim_id, 1, 'night'))
        self.assertEqual(split(self.work.claims, self.work.deliveries, fixture.split_request), fixture.moved)
        self.assertEqual(publish(self.work.candidates, self.work.deliveries, fixture.first), fixture.first_receipt)
        self.assertIsNone(publish(self.work.candidates, self.work.deliveries, fixture.spent))

    def test_interrupted_transfer_then_continue(self):
        fixture = seed(self.work)
        batch_id = fixture.batch_id
        with self.assertRaises(Interrupted):
            handoff(self.work.candidates, self.work.deliveries, 'shift', batch_id, ['wide', 'tail'],
                    after_checkpoint=interrupt)
        # Eligibility left, but the takeover material is not effective yet.
        with self.assertRaises(ValueError):
            publish(self.work.candidates, self.work.deliveries, fixture.tail)
        with self.assertRaises(ValueError):
            publish_offline(self.work.deliveries, 'shift', 'tail')
        self.assertEqual(publish(self.work.candidates, self.work.deliveries, fixture.first), fixture.first_receipt)
        self.assertEqual(split(self.work.claims, self.work.deliveries, fixture.split_request), fixture.moved)
        with self.assertRaises(ValueError):
            handoff(self.work.candidates, self.work.deliveries, 'shift', batch_id, ['wide'])
        # The same id with the same parameters continues on the original checkpoint.
        calls = []
        receipt = handoff(self.work.candidates, self.work.deliveries, 'shift', batch_id, ['tail', 'wide'],
                          after_checkpoint=lambda: calls.append('checkpoint'))
        self.assertEqual(receipt, HandoffReceipt('shift', batch_id, ('tail', 'wide')))
        self.assertEqual(calls, ['checkpoint'])
        night = publish_offline(self.work.deliveries, 'shift', 'tail')
        self.assertEqual(row_details(night.rows), [(1, None, 'night', 102), (2, 11, 'night', 103)])

    def test_detached_offline_signing(self):
        fixture = seed(self.work)
        batch_id = fixture.batch_id
        receipt = handoff(self.work.candidates, self.work.deliveries, 'shift', batch_id, ['wide', 'tail'])
        ledger = detach_catalogue(self.work)
        # The retired catalogue is not needed to re-claim the handoff.
        replay = handoff(self.work.candidates, ledger, 'shift', batch_id, ['tail', 'wide'])
        self.assertEqual(replay, receipt)
        with self.assertRaises(ValueError):
            handoff(self.work.candidates, ledger, 'shift', batch_id, ['tail'])
        with self.assertRaises(ValueError):
            handoff(self.work.candidates, ledger, 'other-shift', batch_id, ['tail'])

        night = publish_offline(ledger, 'shift', 'tail')
        self.assertEqual(night.receipt_id, 'page:tail')
        self.assertEqual(night.request_id, 'tail')
        self.assertEqual(night.batch_id, batch_id)
        self.assertEqual(night.claim_id, fixture.moved.successor.claim_id)
        self.assertEqual(night.group_id, 'night')
        self.assertEqual(row_details(night.rows), [(1, None, 'night', 102), (2, 11, 'night', 103)])
        self.assertEqual([row.source.station for row in night.rows], ['松桥'] * 2)
        self.assertEqual([row.source.document for row in night.rows], ['offline-day'] * 2)
        # The old wide page is formally closed empty.
        self.assertIsNone(publish_offline(ledger, 'shift', 'wide'))
        self.assertIsNone(get_page(ledger, 'page:wide'))
        # The first receipt stays as the original group's 7 L page.
        self.assertEqual(get_page(ledger, 'page:first'), fixture.first_receipt)
        # Re-claiming a signed page returns the same receipt.
        self.assertEqual(publish_offline(ledger, 'shift', 'tail'), night)
        self.assertEqual(get_page(ledger, 'page:tail'), night)
        # Candidates outside the list and unknown handoffs are refused.
        with self.assertRaises(ValueError):
            publish_offline(ledger, 'shift', 'spent')
        with self.assertRaises(ValueError):
            publish_offline(ledger, 'shift', 'first')
        with self.assertRaises(ValueError):
            publish_offline(ledger, 'unknown-shift', 'tail')
        with self.assertRaises(ValueError):
            publish_offline(ledger, '', 'tail')
        with self.assertRaises(ValueError):
            publish_offline(ledger, 'shift', ' ')

        delivered = read_batch_delivery(ledger, batch_id)
        self.assertEqual(
            row_details(delivered),
            [(0, 7, 'day', 101), (1, None, 'night', 102), (2, 11, 'night', 103)],
        )
        litres = [row.litres for row in delivered if row.litres is not None]
        self.assertEqual((len(delivered), len(delivered) - len(litres), sum(litres)), (3, 1, 18))

    def test_offline_commit_boundaries(self):
        fixture = seed(self.work)
        batch_id = fixture.batch_id
        tail2 = self.work.candidate(fixture.moved.successor, 'tail2', 1, 3)
        handoff(self.work.candidates, self.work.deliveries, 'shift', batch_id, ['wide', 'tail', 'tail2'])
        ledger = detach_catalogue(self.work)
        # A failure before the commit rolls the delivery back; the original id can retry.
        with self.assertRaises(Interrupted):
            publish_offline(ledger, 'shift', 'tail', before_commit=interrupt)
        self.assertIsNone(get_page(ledger, 'page:tail'))
        self.assertEqual([row.position for row in read_batch_delivery(ledger, batch_id)], [0])
        # A lost reply after the commit is re-claimed with the same parameters.
        with self.assertRaises(Interrupted):
            publish_offline(ledger, 'shift', 'tail', after_commit=interrupt)
        calls = []
        night = publish_offline(ledger, 'shift', 'tail', after_commit=lambda: calls.append('commit'))
        self.assertEqual(row_details(night.rows), [(1, None, 'night', 102), (2, 11, 'night', 103)])
        self.assertEqual(calls, [])
        # The overlapping listed candidate skips the positions delivered at signing time.
        self.assertIsNone(publish_offline(ledger, 'shift', 'tail2'))
        self.assertIsNone(get_page(ledger, 'page:tail2'))
        delivered = read_batch_delivery(ledger, batch_id)
        self.assertEqual([row.position for row in delivered], [0, 1, 2])

    def test_before_decision_interleaves_split(self):
        fixture = seed(self.work, split_tail=False)

        def interleave():
            other = open_workday(self.root)
            moved = split(other.claims, other.deliveries, fixture.split_request)
            other.candidate(moved.successor, 'tail', 1, 3)

        receipt = handoff(
            self.work.candidates, self.work.deliveries, 'shift', fixture.batch_id, ['wide', 'tail'],
            before_decision=interleave,
        )
        self.assertEqual(receipt.request_ids, ('tail', 'wide'))
        ledger = detach_catalogue(self.work)
        night = publish_offline(ledger, 'shift', 'tail')
        self.assertEqual(row_details(night.rows), [(1, None, 'night', 102), (2, 11, 'night', 103)])
        self.assertIsNone(publish_offline(ledger, 'shift', 'wide'))

    def test_online_delivery_before_checkpoint_is_honored(self):
        fixture = seed(self.work, split_tail=False)

        def sign_tail_first():
            other = open_workday(self.root)
            moved = split(other.claims, other.deliveries, fixture.split_request)
            tail = other.candidate(moved.successor, 'tail', 1, 3)
            publish(other.candidates, other.deliveries, tail)

        handoff(
            self.work.candidates, self.work.deliveries, 'shift', fixture.batch_id, ['wide', 'tail'],
            before_decision=sign_tail_first,
        )
        ledger = detach_catalogue(self.work)
        # The finalized candidate keeps its existing result.
        night = publish_offline(ledger, 'shift', 'tail')
        self.assertEqual(row_details(night.rows), [(1, None, 'night', 102), (2, 11, 'night', 103)])
        self.assertIsNone(publish_offline(ledger, 'shift', 'wide'))
        delivered = read_batch_delivery(ledger, fixture.batch_id)
        self.assertEqual([row.position for row in delivered], [0, 1, 2])
        litres = [row.litres for row in delivered if row.litres is not None]
        self.assertEqual((len(delivered) - len(litres), sum(litres)), (1, 18))


if __name__ == '__main__':
    unittest.main()
