from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from batches.freeze import freeze
from batches.intake import BatchSubmission
from batches.reading import FrozenReading
from batches.source import SourceRef
from batches.store import BatchStore
from claims.assign import assign
from claims.store import ClaimStore
from delivery.store import DeliveryStore
from pages.build import prepare
from pages.request import PageRequest
from pages.store import CandidateStore
from reconcile.report import audit


class Interrupted(RuntimeError):
    pass


def interrupt():
    raise Interrupted('operator did not receive a result')


def station_submission(values, submission_id='station-day'):
    readings = tuple(
        FrozenReading(position, value, SourceRef('松桥', submission_id, 101 + position))
        for position, value in enumerate(values)
    )
    return BatchSubmission(submission_id, readings)


class Workday:
    def __init__(self, root: Path):
        self.batches = BatchStore(root / 'catalogue.sqlite3')
        self.claims = ClaimStore(self.batches)
        self.candidates = CandidateStore(self.claims)
        self.deliveries = DeliveryStore(root / 'delivery.sqlite3')

    def initialize(self):
        for store in (self.batches, self.claims, self.candidates, self.deliveries):
            store.initialize()

    def candidate(self, claim, request_id, start, stop):
        return prepare(self.candidates, PageRequest(request_id, claim.claim_id, start, stop))

    def audit(self, batch_id):
        return audit(self.batches, self.deliveries, batch_id)


class WorkdayCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.work = Workday(self.root)
        self.work.initialize()

    def reopen(self):
        self.work = Workday(self.root)
        return self.work

    def seed(self, values=(7, 11, 13)):
        submission = station_submission(values)
        batch_id = freeze(self.work.batches, submission)
        original = assign(self.work.claims, batch_id, 'day')
        return batch_id, original


def row_details(rows):
    return [(row.position, row.litres, row.group_id, row.source.line) for row in rows]
