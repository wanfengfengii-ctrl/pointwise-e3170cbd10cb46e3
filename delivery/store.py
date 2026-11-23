import sqlite3
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path

from batches.reading import FrozenReading
from delivery.receipts import PageReceipt
from delivery.rows import DeliveredRow
from pages.store import CandidatePage


class DeliveryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).absolute()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, isolation_level=None)
        db.execute('PRAGMA foreign_keys = ON')
        return db

    def reader(self, db: sqlite3.Connection | None = None):
        if db is not None:
            return nullcontext(db)
        return closing(self.connect())

    @contextmanager
    def transaction(self):
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            yield db

    def initialize(self) -> None:
        with self.reader() as db:
            db.executescript('''
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS receipts (
                    receipt_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    batch_id TEXT NOT NULL,
                    claim_id TEXT NOT NULL,
                    group_id TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS receipts_by_batch ON receipts (batch_id);
                CREATE TABLE IF NOT EXISTS delivered_rows (
                    receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id),
                    position INTEGER NOT NULL CHECK (position >= 0),
                    litres TEXT,
                    station TEXT NOT NULL,
                    document TEXT NOT NULL,
                    source_line TEXT NOT NULL,
                    PRIMARY KEY (receipt_id, position)
                );
                CREATE TABLE IF NOT EXISTS publications (
                    request_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    claim_id TEXT NOT NULL,
                    start INTEGER NOT NULL,
                    stop INTEGER NOT NULL CHECK (stop > start),
                    receipt_id TEXT UNIQUE REFERENCES receipts(receipt_id)
                );
                COMMIT;
            ''')

    def write_delivery(
        self, page: CandidatePage, receipt: PageReceipt | None, *, db: sqlite3.Connection
    ) -> None:
        """Save an adjudicated result inside the publication's write transaction."""
        if receipt is not None:
            db.execute(
                '''INSERT INTO receipts (receipt_id, request_id, batch_id, claim_id, group_id)
                   VALUES (?, ?, ?, ?, ?)''',
                (receipt.receipt_id, receipt.request_id, receipt.batch_id, receipt.claim_id, receipt.group_id),
            )
            db.executemany(
                '''INSERT INTO delivered_rows (receipt_id, position, litres, station, document, source_line)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                ((receipt.receipt_id, *row.reading.storage_values()) for row in receipt.rows),
            )
        request = page.request
        db.execute(
            '''INSERT INTO publications (request_id, batch_id, claim_id, start, stop, receipt_id)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (
                request.request_id, page.batch_id, request.claim_id, request.start, request.stop,
                None if receipt is None else receipt.receipt_id,
            ),
        )

    def get_publication_record(
        self, request_id: str, *, db: sqlite3.Connection | None = None
    ) -> tuple[str, str, int, int, str | None] | None:
        with self.reader(db) as connection:
            return connection.execute(
                'SELECT batch_id, claim_id, start, stop, receipt_id FROM publications WHERE request_id = ?',
                (request_id,),
            ).fetchone()

    def get_committed_page(
        self, receipt_id: str, *, db: sqlite3.Connection | None = None
    ) -> PageReceipt | None:
        with self.reader(db) as connection:
            header = connection.execute(
                'SELECT request_id, batch_id, claim_id, group_id FROM receipts WHERE receipt_id = ?',
                (receipt_id,),
            ).fetchone()
            if header is None:
                return None
            request_id, batch_id, claim_id, group_id = header
            records = connection.execute(
                '''SELECT position, litres, station, document, source_line FROM delivered_rows
                   WHERE receipt_id = ? ORDER BY position''',
                (receipt_id,),
            )
            rows = tuple(
                DeliveredRow(batch_id, claim_id, group_id, FrozenReading.from_storage(*record))
                for record in records
            )
            return PageReceipt(receipt_id, request_id, batch_id, claim_id, group_id, rows)

    def get_committed_rows(
        self, batch_id: str, *, db: sqlite3.Connection | None = None
    ) -> tuple[DeliveredRow, ...]:
        with self.reader(db) as connection:
            records = connection.execute(
                '''SELECT p.claim_id, p.group_id, r.position, r.litres, r.station, r.document, r.source_line
                   FROM receipts AS p JOIN delivered_rows AS r USING (receipt_id)
                   WHERE p.batch_id = ? ORDER BY r.position, p.receipt_id''',
                (batch_id,),
            )
            return tuple(
                DeliveredRow(batch_id, claim_id, group_id, FrozenReading.from_storage(*reading))
                for claim_id, group_id, *reading in records
            )

    def has_committed_rows(self, batch_id: str, start: int, stop: int) -> bool:
        with self.reader() as db:
            row = db.execute(
                '''SELECT 1 FROM receipts AS p JOIN delivered_rows AS r USING (receipt_id)
                   WHERE p.batch_id = ? AND r.position >= ? AND r.position < ? LIMIT 1''',
                (batch_id, start, stop),
            ).fetchone()
            return row is not None
