import sqlite3
from dataclasses import dataclass

from claims.store import ClaimStore
from pages.request import PageRequest


@dataclass(frozen=True, slots=True)
class CandidatePage:
    request: PageRequest
    batch_id: str
    positions: tuple[int, ...]


class CandidateStore:
    def __init__(self, claims: ClaimStore):
        self.claims = claims

    def initialize(self) -> None:
        with self.claims.batches.reader() as db:
            db.executescript('''
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS candidate_pages (
                    request_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
                    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                    start INTEGER NOT NULL,
                    stop INTEGER NOT NULL CHECK (stop > start)
                );
                CREATE TABLE IF NOT EXISTS candidate_positions (
                    request_id TEXT NOT NULL REFERENCES candidate_pages(request_id),
                    batch_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (request_id, position),
                    FOREIGN KEY (batch_id, position) REFERENCES frozen_rows(batch_id, position)
                );
                COMMIT;
            ''')

    def save_candidate(self, page: CandidatePage, *, db: sqlite3.Connection) -> None:
        request = page.request
        db.execute(
            '''INSERT INTO candidate_pages (request_id, claim_id, batch_id, start, stop)
               VALUES (?, ?, ?, ?, ?)''',
            (request.request_id, request.claim_id, page.batch_id, request.start, request.stop),
        )
        db.executemany(
            'INSERT INTO candidate_positions (request_id, batch_id, position) VALUES (?, ?, ?)',
            ((request.request_id, page.batch_id, position) for position in page.positions),
        )

    def get_candidate(self, request_id: str, *, db: sqlite3.Connection | None = None) -> CandidatePage | None:
        with self.claims.batches.reader(db) as connection:
            header = connection.execute(
                'SELECT claim_id, batch_id, start, stop FROM candidate_pages WHERE request_id = ?',
                (request_id,),
            ).fetchone()
            if header is None:
                return None
            claim_id, batch_id, start, stop = header
            rows = connection.execute(
                'SELECT position FROM candidate_positions WHERE request_id = ? ORDER BY position',
                (request_id,),
            )
            return CandidatePage(PageRequest(request_id, claim_id, start, stop), batch_id, tuple(row[0] for row in rows))
