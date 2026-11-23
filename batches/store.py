import sqlite3
from contextlib import closing, contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path

from batches.reading import FrozenReading


@dataclass(frozen=True, slots=True)
class FrozenBatch:
    batch_id: str
    submission_id: str
    rows: tuple[FrozenReading, ...]


class BatchStore:
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
        with closing(self.connect()) as db:
            db.executescript('''
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY,
                    submission_id TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS frozen_rows (
                    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                    position INTEGER NOT NULL CHECK (position >= 0),
                    litres TEXT,
                    station TEXT NOT NULL,
                    document TEXT NOT NULL,
                    source_line TEXT NOT NULL,
                    PRIMARY KEY (batch_id, position)
                );
                COMMIT;
            ''')

    def insert_batch(self, batch: FrozenBatch) -> str:
        with self.transaction() as db:
            existing = self.get_batch(batch.batch_id, db=db)
            if existing is not None:
                if existing != batch:
                    raise ValueError('submission_id already identifies different readings')
                return existing.batch_id

            db.execute(
                'INSERT INTO batches (batch_id, submission_id) VALUES (?, ?)',
                (batch.batch_id, batch.submission_id),
            )
            db.executemany(
                '''INSERT INTO frozen_rows
                   (batch_id, position, litres, station, document, source_line)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                ((batch.batch_id, *row.storage_values()) for row in batch.rows),
            )
        return batch.batch_id

    def get_batch(self, batch_id: str, *, db: sqlite3.Connection | None = None) -> FrozenBatch | None:
        with self.reader(db) as connection:
            header = connection.execute(
                'SELECT submission_id FROM batches WHERE batch_id = ?', (batch_id,)
            ).fetchone()
            if header is None:
                return None
            rows = connection.execute(
                '''SELECT position, litres, station, document, source_line
                   FROM frozen_rows WHERE batch_id = ? ORDER BY position''',
                (batch_id,),
            )
            return FrozenBatch(batch_id, header[0], tuple(FrozenReading.from_storage(*row) for row in rows))
