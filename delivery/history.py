from batches.source import require_label
from delivery.rows import DeliveredRow
from delivery.store import DeliveryStore


def read_batch_delivery(store: DeliveryStore, batch_id: str) -> tuple[DeliveredRow, ...]:
    require_label(batch_id, 'batch_id')
    return store.get_committed_rows(batch_id)
