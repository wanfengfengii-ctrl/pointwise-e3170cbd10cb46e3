from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from batches.source import require_label
from delivery.rows import DeliveredRow

if TYPE_CHECKING:
    from delivery.store import DeliveryStore
    from pages.store import CandidatePage


@dataclass(frozen=True, slots=True)
class PageReceipt:
    receipt_id: str
    request_id: str
    batch_id: str
    claim_id: str
    group_id: str
    rows: tuple[DeliveredRow, ...]


def build_receipt(request_id: str, rows: tuple[DeliveredRow, ...]) -> PageReceipt:
    if not rows:
        raise ValueError('a successful receipt requires delivered rows')
    first = rows[0]
    return PageReceipt(f'page:{request_id}', request_id, first.batch_id, first.claim_id, first.group_id, rows)


def recover_publication(
    store: DeliveryStore, page: CandidatePage, *, db: sqlite3.Connection
) -> tuple[bool, PageReceipt | None]:
    record = store.get_publication_record(page.request.request_id, db=db)
    if record is None:
        return False, None
    batch_id, claim_id, start, stop, receipt_id = record
    if batch_id != page.batch_id or (claim_id, start, stop) != page.request.fingerprint():
        raise ValueError('publication request_id already bound to other parameters')
    if receipt_id is None:
        return True, None
    receipt = store.get_committed_page(receipt_id, db=db)
    if receipt is None:
        raise RuntimeError('publication record has no matching receipt')
    return True, receipt


def get_page(store: DeliveryStore, receipt_id: str) -> PageReceipt | None:
    require_label(receipt_id, 'receipt_id')
    return store.get_committed_page(receipt_id)
