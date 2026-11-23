from collections.abc import Callable

from claims.transfer import get_batch_transfer
from delivery.receipts import PageReceipt, build_receipt, recover_publication
from delivery.rows import materialize_rows
from delivery.store import DeliveryStore
from pages.store import CandidatePage, CandidateStore
from pages.validate import validate_candidate


def publish(
    candidates: CandidateStore,
    deliveries: DeliveryStore,
    page: CandidatePage,
    *,
    before_decision: Callable[[], None] | None = None,
    before_commit: Callable[[], None] | None = None,
    after_commit: Callable[[], None] | None = None,
) -> PageReceipt | None:
    # Prepared requests and frozen rows are immutable, so they can be read early.
    prepared_rows = validate_candidate(candidates, page)
    if before_decision is not None:
        before_decision()

    claims = candidates.claims
    with claims.transaction() as catalogue:
        with deliveries.transaction() as ledger:
            found, prior = recover_publication(deliveries, page, db=ledger)
            if found:
                return prior

            if get_batch_transfer(catalogue, page.batch_id) is not None:
                raise ValueError('batch eligibility was transferred to an offline handoff')
            claim = claims.get_claim(page.request.claim_id, db=catalogue)
            if claim is None or claim.batch_id != page.batch_id:
                raise ValueError('candidate has no matching claim for this batch')
            occupied = {row.position for row in deliveries.get_committed_rows(page.batch_id, db=ledger)}
            eligible = (
                row for row in prepared_rows
                if claim.span.contains(row.position) and row.position not in occupied
            )
            rows = materialize_rows(claim, eligible)
            receipt = build_receipt(page.request.request_id, rows) if rows else None
            deliveries.write_delivery(page, receipt, db=ledger)
            if before_commit is not None:
                before_commit()
        # The ledger commit precedes release of the catalogue's eligibility lock.

    if after_commit is not None:
        after_commit()
    return receipt
