from collections.abc import Iterable

from batches.store import FrozenBatch
from delivery.rows import DeliveredRow


def verify_provenance(batch: FrozenBatch, rows: Iterable[DeliveredRow]) -> None:
    for row in rows:
        if row.batch_id != batch.batch_id or not 0 <= row.position < len(batch.rows):
            raise ValueError('no frozen origin for delivered row')
        original = batch.rows[row.position]
        if row.reading != original:
            raise ValueError(f'delivered value or source differs at original position {row.position}')
