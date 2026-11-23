from dataclasses import dataclass

from batches.source import require_label
from batches.store import BatchStore
from delivery.history import read_batch_delivery
from delivery.rows import DeliveredRow
from delivery.store import DeliveryStore
from reconcile.coverage import compare_coverage
from reconcile.provenance import verify_provenance
from reconcile.totals import GroupTotals, summarize_totals


@dataclass(frozen=True, slots=True)
class AuditReport:
    batch_id: str
    delivered: tuple[DeliveredRow, ...]
    undelivered_positions: tuple[int, ...]
    groups: tuple[tuple[str, GroupTotals], ...]
    total: GroupTotals


def audit(batches: BatchStore, deliveries: DeliveryStore, batch_id: str) -> AuditReport:
    require_label(batch_id, 'batch_id')
    batch = batches.get_batch(batch_id)
    if batch is None:
        raise LookupError(f'unknown batch {batch_id!r}')
    coverage = compare_coverage(batch, read_batch_delivery(deliveries, batch_id))
    verify_provenance(batch, coverage.delivered)
    groups, total = summarize_totals(coverage.delivered)
    return AuditReport(batch_id, coverage.delivered, coverage.undelivered_positions, groups, total)
