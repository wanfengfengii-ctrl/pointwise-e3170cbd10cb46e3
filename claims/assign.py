from batches.source import require_label
from claims.ranges import ClaimRange
from claims.store import Claim, ClaimStore


def assign(claims: ClaimStore, batch_id: str, group_id: str) -> Claim:
    require_label(batch_id, 'batch_id')
    require_label(group_id, 'group_id')
    with claims.transaction() as db:
        batch = claims.batches.get_batch(batch_id, db=db)
        if batch is None:
            raise LookupError(f'unknown batch {batch_id!r}')
        original = Claim(f'original:{batch_id}', batch_id, group_id, ClaimRange(0, len(batch.rows)))
        return claims.insert_original(original, db=db)
