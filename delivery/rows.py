from collections.abc import Iterable
from dataclasses import dataclass

from batches.reading import FrozenReading
from batches.source import SourceRef
from claims.store import Claim


@dataclass(frozen=True, slots=True)
class DeliveredRow:
    batch_id: str
    claim_id: str
    group_id: str
    reading: FrozenReading

    @property
    def position(self) -> int:
        return self.reading.position

    @property
    def litres(self) -> int | None:
        return self.reading.litres

    @property
    def source(self) -> SourceRef:
        return self.reading.source


def materialize_rows(claim: Claim, readings: Iterable[FrozenReading]) -> tuple[DeliveredRow, ...]:
    return tuple(DeliveredRow(claim.batch_id, claim.claim_id, claim.group_id, reading) for reading in readings)
