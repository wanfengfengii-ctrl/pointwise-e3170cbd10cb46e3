"""Catalogue-side record of batch eligibility transferred to an offline handoff."""
import json
import sqlite3


TRANSFER_DDL = '''
    CREATE TABLE IF NOT EXISTS handoff_transfers (
        handoff_id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL UNIQUE,
        request_ids TEXT NOT NULL,
        material TEXT NOT NULL
    );
'''


def get_transfer(db: sqlite3.Connection, handoff_id: str) -> tuple[str, tuple[str, ...], str] | None:
    row = db.execute(
        'SELECT batch_id, request_ids, material FROM handoff_transfers WHERE handoff_id = ?',
        (handoff_id,),
    ).fetchone()
    if row is None:
        return None
    batch_id, request_ids, material = row
    return batch_id, tuple(json.loads(request_ids)), material


def get_batch_transfer(db: sqlite3.Connection, batch_id: str) -> str | None:
    row = db.execute(
        'SELECT handoff_id FROM handoff_transfers WHERE batch_id = ?', (batch_id,)
    ).fetchone()
    return None if row is None else row[0]


def record_transfer(
    db: sqlite3.Connection, handoff_id: str, batch_id: str, request_ids: tuple[str, ...], material: str
) -> None:
    db.execute(
        'INSERT INTO handoff_transfers (handoff_id, batch_id, request_ids, material) VALUES (?, ?, ?, ?)',
        (handoff_id, batch_id, json.dumps(list(request_ids), ensure_ascii=False), material),
    )
