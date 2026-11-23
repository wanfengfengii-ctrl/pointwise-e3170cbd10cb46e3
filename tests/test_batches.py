from dataclasses import replace

from batches.freeze import freeze
from batches.intake import BatchSubmission
from batches.source import SourceRef
from claims.assign import assign
from claims.ranges import ClaimRange
from tests.support import WorkdayCase, station_submission


class FreezeTests(WorkdayCase):
    def test_frozen_positions(self):
        submission = station_submission((7, 7))
        batch_id = freeze(self.work.batches, submission)
        claim = assign(self.work.claims, batch_id, 'day')
        frozen = self.work.batches.get_batch(batch_id)
        self.assertEqual(frozen.rows, submission.readings)
        self.assertEqual([(r.position, r.litres, r.source.line) for r in frozen.rows], [(0, 7, 101), (1, 7, 102)])
        self.assertEqual(claim.span, ClaimRange(0, 2))
        self.assertEqual(self.work.candidate(claim, 'equal-readings', 0, 2).positions, (0, 1))

    def test_duplicate_position(self):
        submission = station_submission((7, 11))
        first, second = submission.readings
        repeated = BatchSubmission(submission.submission_id, (first, replace(second, position=0)))
        with self.assertRaises(ValueError):
            freeze(self.work.batches, repeated)
        self.assertIsNone(self.work.batches.get_batch('batch:station-day'))
        with self.assertRaises(LookupError):
            assign(self.work.claims, 'batch:station-day', 'day')

    def test_non_integer_litres(self):
        for value in (7.5, True, '7'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    freeze(self.work.batches, station_submission((7, value)))
                self.assertIsNone(self.work.batches.get_batch('batch:station-day'))

    def test_assign_conflict(self):
        batch_id, original = self.seed()
        with self.assertRaises(LookupError):
            assign(self.work.claims, 'unknown', 'day')
        with self.assertRaises(ValueError):
            assign(self.work.claims, batch_id, 'night')
        self.assertEqual(assign(self.work.claims, batch_id, 'day'), original)
        self.assertEqual(self.work.claims.list_claims(batch_id), (original,))
        self.assertEqual(self.work.claims.list_claims('unknown'), ())

    def test_insufficient_provenance(self):
        submission = station_submission((None,))
        for source in (SourceRef('', 'report', 1), SourceRef('station', ' ', 1), SourceRef('station', 'report', 0)):
            with self.subTest(source=source):
                row = replace(submission.readings[0], source=source)
                with self.assertRaises(ValueError):
                    freeze(self.work.batches, replace(submission, readings=(row,)))
                self.assertIsNone(self.work.batches.get_batch('batch:station-day'))

    def test_intake_replay_cannot_change_frozen_readings(self):
        submission = station_submission((0, 11))
        batch_id = freeze(self.work.batches, submission)
        self.assertEqual(freeze(self.work.batches, submission), batch_id)
        with self.assertRaises(ValueError):
            freeze(self.work.batches, station_submission((0, 13)))
        self.assertEqual(self.work.batches.get_batch(batch_id).rows, submission.readings)
