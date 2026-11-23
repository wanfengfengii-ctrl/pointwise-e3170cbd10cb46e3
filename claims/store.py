from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from batches.store import BatchStore
from claims.ranges import ClaimRange

if TYPE_CHECKING:
    from claims.receipt import SplitRequest


@dataclass(frozen=True, slots=True)
class Claim:
    claim_id: str
    batch_id: str
    group_id: str
    span: ClaimRange
    parent_id: str | None = None


class ClaimStore:
    def __init__(self, batches: BatchStore):
        self.batches = batches

    def transaction(self):
        return self.batches.transaction()

    def initialize(self) -> None:
        with self.batches.reader() as db:
            db.executescript('''
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                    group_id TEXT NOT NULL,
                    start INTEGER NOT NULL CHECK (start >= 0),
                    stop INTEGER NOT NULL CHECK (stop >= start),
                    parent_id TEXT UNIQUE REFERENCES claims(claim_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_original_claim
                    ON claims (batch_id) WHERE parent_id IS NULL;
                CREATE TABLE IF NOT EXISTS split_requests (
                    request_id TEXT PRIMARY KEY,
                    parent_id TEXT NOT NULL UNIQUE REFERENCES claims(claim_id),
                    boundary INTEGER NOT NULL,
                    successor_group TEXT NOT NULL,
                    successor_id TEXT NOT NULL UNIQUE REFERENCES claims(claim_id)
                );
                COMMIT;
            ''')

    @staticmethod
    def _read_claim(row: tuple) -> Claim:
        claim_id, batch_id, group_id, start, stop, parent_id = row
        return Claim(claim_id, batch_id, group_id, ClaimRange(start, stop), parent_id)

    def get_claim(self, claim_id: str, *, db: sqlite3.Connection | None = None) -> Claim | None:
        with self.batches.reader(db) as connection:
            row = connection.execute(
                '''SELECT claim_id, batch_id, group_id, start, stop, parent_id
                   FROM claims WHERE claim_id = ?''',
                (claim_id,),
            ).fetchone()
            return None if row is None else self._read_claim(row)

    def list_claims(self, batch_id: str) -> tuple[Claim, ...]:
        with self.batches.reader() as db:
            rows = db.execute(
                '''SELECT claim_id, batch_id, group_id, start, stop, parent_id
                   FROM claims WHERE batch_id = ? ORDER BY parent_id IS NOT NULL, claim_id''',
                (batch_id,),
            )
            return tuple(self._read_claim(row) for row in rows)

    def has_split(self, claim_id: str, *, db: sqlite3.Connection) -> bool:
        row = db.execute('SELECT 1 FROM split_requests WHERE parent_id = ?', (claim_id,)).fetchone()
        return row is not None

    def _insert_claim(self, claim: Claim, db: sqlite3.Connection) -> None:
        db.execute(
            '''INSERT INTO claims (claim_id, batch_id, group_id, start, stop, parent_id)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (claim.claim_id, claim.batch_id, claim.group_id, claim.span.start, claim.span.stop, claim.parent_id),
        )

    def insert_original(self, claim: Claim, *, db: sqlite3.Connection) -> Claim:
        existing = self.get_claim(claim.claim_id, db=db)
        if existing is not None:
            if existing.group_id != claim.group_id:
                raise ValueError('batch already belongs to another original group')
            return existing
        self._insert_claim(claim, db)
        return claim

    def write_split(
        self, request: SplitRequest, retained: Claim, successor: Claim, *, db: sqlite3.Connection
    ) -> None:
        db.execute(
            'UPDATE claims SET stop = ? WHERE claim_id = ?',
            (retained.span.stop, retained.claim_id),
        )
        self._insert_claim(successor, db)
        db.execute(
            '''INSERT INTO split_requests (request_id, parent_id, boundary, successor_group, successor_id)
               VALUES (?, ?, ?, ?, ?)''',
            (request.request_id, retained.claim_id, request.boundary, request.successor_group, successor.claim_id),
        )

    def get_split_record(
        self, request_id: str, *, db: sqlite3.Connection | None = None
    ) -> tuple[str, int, str, str] | None:
        with self.batches.reader(db) as connection:
            return connection.execute(
                '''SELECT parent_id, boundary, successor_group, successor_id
                   FROM split_requests WHERE request_id = ?''',
                (request_id,),
            ).fetchone()
