from delivery.publish import publish
from reconcile.totals import GroupTotals
from tests.support import WorkdayCase, row_details


class AuditTests(WorkdayCase):
    def _out_of_order_batch(self):
        batch_id, original = self.seed((7, None, 7, 0, 11))
        upper = self.work.candidate(original, 'upper', 2, 4)
        lower = self.work.candidate(original, 'lower', 0, 2)
        first = publish(self.work.candidates, self.work.deliveries, upper)
        second = publish(self.work.candidates, self.work.deliveries, lower)
        return self.work.audit(batch_id), first, second

    def test_missing_and_undelivered(self):
        report, _, _ = self._out_of_order_batch()
        self.assertEqual([(row.position, row.source.line) for row in report.delivered if row.litres is None], [(1, 102)])
        self.assertEqual(report.total, GroupTotals(4, 1, 14))
        self.assertEqual(report.undelivered_positions, (4,))

    def test_ordered_positions(self):
        report, first, second = self._out_of_order_batch()
        self.assertEqual([row.position for row in first.rows + second.rows], [2, 3, 0, 1])
        self.assertEqual(row_details(report.delivered), [(0, 7, 'day', 101), (1, None, 'day', 102), (2, 7, 'day', 103), (3, 0, 'day', 104)])
        self.assertEqual([row.source.document for row in report.delivered], ['station-day'] * 4)

    def test_grouped_multiple_pages(self):
        report, first, second = self._out_of_order_batch()
        self.assertEqual([row.litres for row in first.rows], [7, 0])
        self.assertEqual([row.litres for row in second.rows], [7, None])
        self.assertEqual(report.groups, (('day', GroupTotals(4, 1, 14)),))
        self.assertEqual(report.total, GroupTotals(4, 1, 14))

    def test_empty_delivery(self):
        batch_id, original = self.seed((None, 0, 13))
        self.work.candidate(original, 'waiting', 0, 2)
        report = self.work.audit(batch_id)
        self.assertEqual(report.delivered, ())
        self.assertEqual(report.undelivered_positions, (0, 1, 2))
        self.assertEqual(report.groups, ())
        self.assertEqual(report.total, GroupTotals(0, 0, 0))

    def test_unknown_batch(self):
        with self.assertRaises(LookupError):
            self.work.audit('batch:unknown')

    def test_exact_integer_totals(self):
        litres = 2 ** 90
        batch_id, original = self.seed((litres, None, 7))
        page = self.work.candidate(original, 'wide', 0, 3)
        publish(self.work.candidates, self.work.deliveries, page)
        self.reopen()
        report = self.work.audit(batch_id)
        self.assertEqual([row.litres for row in report.delivered], [litres, None, 7])
        self.assertEqual(report.total, GroupTotals(3, 1, litres + 7))
