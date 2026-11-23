from collections.abc import Callable
from dataclasses import replace

from claims.ranges import partition_range
from claims.receipt import SplitReceipt, SplitRequest, recover_split
from claims.store import Claim, ClaimStore
from claims.transfer import get_batch_transfer
from delivery.store import DeliveryStore


def split(
    claims: ClaimStore,
    deliveries: DeliveryStore,
    request: SplitRequest,
    *,
    before_decision: Callable[[], None] | None = None,
    after_commit: Callable[[], None] | None = None,
) -> SplitReceipt:
    if before_decision is not None:
        before_decision()

    # Publication holds this same write lock until its delivery commit finishes.
    with claims.transaction() as catalogue:
        prior = recover_split(claims, request, db=catalogue)
        if prior is not None:
            return prior

        parent = claims.get_claim(request.claim_id, db=catalogue)
        if parent is None:
            raise LookupError(f'unknown claim {request.claim_id!r}')
        if get_batch_transfer(catalogue, parent.batch_id) is not None:
            raise ValueError('batch eligibility was transferred to an offline handoff')
        if parent.parent_id is not None or claims.has_split(parent.claim_id, db=catalogue):
            raise ValueError('only the original claim may be split once')
        if request.successor_group == parent.group_id:
            raise ValueError('successor group must differ from the original group')

        retained_span, tail = partition_range(parent.span, request.boundary)
        if deliveries.has_committed_rows(parent.batch_id, tail.start, tail.stop):
            raise ValueError('tail already delivered')

        retained = replace(parent, span=retained_span)
        successor = Claim(
            f'successor:{parent.batch_id}', parent.batch_id, request.successor_group, tail, parent.claim_id
        )
        claims.write_split(request, retained, successor, db=catalogue)
        receipt = SplitReceipt(request, retained, successor)

    if after_commit is not None:
        after_commit()
    return receipt
