import sqlite3

from batches.reading import FrozenReading
from claims.ranges import ClaimRange, positions_in_range
from claims.store import ClaimStore
from pages.request import PageRequest


def select_candidate_rows(
    claims: ClaimStore, request: PageRequest, *, db: sqlite3.Connection
) -> tuple[str, tuple[FrozenReading, ...]]:
    claim = claims.get_claim(request.claim_id, db=db)
    if claim is None:
        raise LookupError(f'unknown claim {request.claim_id!r}')
    span = ClaimRange(request.start, request.stop)
    if not claim.span.covers(span):
        raise ValueError('candidate range exceeds the current claim')
    batch = claims.batches.get_batch(claim.batch_id, db=db)
    if batch is None:
        raise RuntimeError('claim has no frozen batch')
    return batch.batch_id, tuple(batch.rows[position] for position in positions_in_range(span))
