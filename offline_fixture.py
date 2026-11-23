from dataclasses import dataclass
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from batches.freeze import freeze
from claims.assign import assign
from claims.receipt import SplitReceipt, SplitRequest
from claims.split import split
from claims.store import Claim
from delivery.history import read_batch_delivery
from delivery.publish import publish
from delivery.receipts import PageReceipt, get_page
from delivery.store import DeliveryStore
from pages.store import CandidatePage
from tests.support import Workday, row_details, station_submission


@dataclass(frozen=True, slots=True)
class HandoffFixture:
    batch_id: str
    original: Claim
    wide: CandidatePage
    first: CandidatePage
    first_receipt: PageReceipt
    spent: CandidatePage
    split_request: SplitRequest
    moved: SplitReceipt | None
    tail: CandidatePage | None


def open_workday(root: Path) -> Workday:
    work = Workday(root / "catalogue")
    work.deliveries = DeliveryStore(root / "archive" / "delivery.sqlite3")
    return work


def create_workday(root: Path) -> Workday:
    (root / "catalogue").mkdir()
    (root / "archive").mkdir()
    work = open_workday(root)
    work.initialize()
    return work


def seed(work: Workday, *, split_tail: bool = True) -> HandoffFixture:
    batch_id = freeze(work.batches, station_submission((7, None, 11), "offline-day"))
    original = assign(work.claims, batch_id, "day")
    wide = work.candidate(original, "wide", 0, 3)
    first = work.candidate(original, "first", 0, 1)
    first_receipt = publish(work.candidates, work.deliveries, first)
    if first_receipt is None:
        raise AssertionError("the first original position must already be signed")
    spent = work.candidate(original, "spent", 0, 1)
    if publish(work.candidates, work.deliveries, spent) is not None:
        raise AssertionError("the already occupied candidate must be closed empty")
    request = SplitRequest("move-tail", original.claim_id, 1, "night")
    moved = split(work.claims, work.deliveries, request) if split_tail else None
    tail = work.candidate(moved.successor, "tail", 1, 3) if moved is not None else None
    return HandoffFixture(batch_id, original, wide, first, first_receipt, spent, request, moved, tail)


def detach_catalogue(work: Workday) -> DeliveryStore:
    catalogue = work.batches.path.parent
    catalogue.rename(catalogue.with_name("retired-catalogue"))
    return DeliveryStore(work.deliveries.path)


def main() -> None:
    with TemporaryDirectory(prefix="qinglan-offline-fixture-") as directory:
        work = create_workday(Path(directory))
        fixture = seed(work)
        tail = fixture.tail
        report = work.audit(fixture.batch_id)
        if tail is None or tail.positions != (1, 2) or fixture.wide.positions != (0, 1, 2):
            raise AssertionError("expected two prepared pages with overlapping coordinates")
        if report.undelivered_positions != (1, 2) or report.total.litres != 7:
            raise AssertionError(f"unexpected initial delivery report: {report!r}")
        ledger = detach_catalogue(work)
        first = get_page(ledger, fixture.first_receipt.receipt_id)
        if first != fixture.first_receipt or row_details(first.rows) != [(0, 7, "day", 101)]:
            raise AssertionError(f"unexpected detached first receipt: {first!r}")
        try:
            publish(work.candidates, ledger, tail)
        except sqlite3.OperationalError as error:
            if error.sqlite_errorcode != sqlite3.SQLITE_CANTOPEN:
                raise
        else:
            raise AssertionError("V1 unexpectedly published the detached tail")
        if read_batch_delivery(ledger, fixture.batch_id) != first.rows:
            raise AssertionError("the V1 control case must leave only the first signed row")
        print(f"V1 {fixture.batch_id}: receipt={first.receipt_id}, rows={row_details(first.rows)}, awaiting={tail.positions}")


if __name__ == "__main__":
    main()
