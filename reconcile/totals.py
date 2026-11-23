from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from delivery.rows import DeliveredRow


@dataclass(frozen=True, slots=True)
class GroupTotals:
    delivered_count: int
    missing_count: int
    litres: int


def _measure(rows: Sequence[DeliveredRow]) -> GroupTotals:
    readings = [row.litres for row in rows if row.litres is not None]
    return GroupTotals(len(rows), len(rows) - len(readings), sum(readings))


def summarize_totals(
    rows: Iterable[DeliveredRow],
) -> tuple[tuple[tuple[str, GroupTotals], ...], GroupTotals]:
    by_group: dict[str, list[DeliveredRow]] = defaultdict(list)
    for row in rows:
        by_group[row.group_id].append(row)
    groups = tuple((group, _measure(by_group[group])) for group in sorted(by_group))
    whole = GroupTotals(
        sum(totals.delivered_count for _, totals in groups),
        sum(totals.missing_count for _, totals in groups),
        sum(totals.litres for _, totals in groups),
    )
    return groups, whole
