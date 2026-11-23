from collections.abc import Iterable
from dataclasses import dataclass

from batches.store import FrozenBatch
from delivery.rows import DeliveredRow


@dataclass(frozen=True, slots=True)
class Coverage:
    delivered: tuple[DeliveredRow, ...]
    undelivered_positions: tuple[int, ...]


def compare_coverage(batch: FrozenBatch, delivered: Iterable[DeliveredRow]) -> Coverage:
    by_position = {}
    for row in delivered:
        if row.batch_id != batch.batch_id or not 0 <= row.position < len(batch.rows):
            raise ValueError('delivered row does not belong to this frozen batch')
        if row.position in by_position:
            raise ValueError(f'duplicate formal delivery at original position {row.position}')
        by_position[row.position] = row

    ordered = []
    undelivered = []
    for original in batch.rows:
        actual = by_position.get(original.position)
        if actual is None:
            undelivered.append(original.position)
        else:
            ordered.append(actual)
    return Coverage(tuple(ordered), tuple(undelivered))
