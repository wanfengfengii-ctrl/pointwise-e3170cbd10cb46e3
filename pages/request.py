from dataclasses import dataclass

from batches.source import require_label
from claims.ranges import ClaimRange


@dataclass(frozen=True, slots=True)
class PageRequest:
    request_id: str
    claim_id: str
    start: int
    stop: int

    def __post_init__(self) -> None:
        require_label(self.request_id, 'page request_id')
        require_label(self.claim_id, 'claim_id')
        span = ClaimRange(self.start, self.stop)
        if span.start == span.stop:
            raise ValueError('a candidate page requires a nonempty range')

    def fingerprint(self) -> tuple[str, int, int]:
        return self.claim_id, self.start, self.stop
