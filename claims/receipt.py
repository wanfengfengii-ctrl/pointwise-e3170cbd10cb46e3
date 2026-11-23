import sqlite3
from dataclasses import dataclass

from batches.source import require_label
from claims.store import Claim, ClaimStore


@dataclass(frozen=True, slots=True)
class SplitRequest:
    request_id: str
    claim_id: str
    boundary: int
    successor_group: str

    def __post_init__(self) -> None:
        require_label(self.request_id, 'split request_id')
        require_label(self.claim_id, 'claim_id')
        require_label(self.successor_group, 'successor_group')
        if type(self.boundary) is not int or self.boundary < 0:
            raise ValueError('split boundary must be a nonnegative integer')


@dataclass(frozen=True, slots=True)
class SplitReceipt:
    request: SplitRequest
    parent: Claim
    successor: Claim


def recover_split(claims: ClaimStore, request: SplitRequest, *, db: sqlite3.Connection) -> SplitReceipt | None:
    stored = claims.get_split_record(request.request_id, db=db)
    if stored is None:
        return None
    parent_id, boundary, group_id, successor_id = stored
    if (parent_id, boundary, group_id) != (request.claim_id, request.boundary, request.successor_group):
        raise ValueError('split request_id already bound to other parameters')
    parent = claims.get_claim(parent_id, db=db)
    successor = claims.get_claim(successor_id, db=db)
    if parent is None or successor is None:
        raise RuntimeError('recorded split is missing a work claim')
    return SplitReceipt(request, parent, successor)
