from dataclasses import dataclass
import sqlite3

from lake.wire import dump, load, require_text
from .rows import row_data, rows_from_data
from .validation import ValidatedBatch


@dataclass(frozen=True)
class SubmissionReceipt:
    batch_id: str
    revision_id: str
    row_count: int
    missing_count: int


@dataclass(frozen=True)
class StoredSubmission:
    batch: ValidatedBatch
    fingerprint: str
    receipt: SubmissionReceipt


def init_station_store(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS station_submission (
            batch_id TEXT PRIMARY KEY NOT NULL,
            station TEXT NOT NULL,
            day TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            original_rows BLOB NOT NULL,
            revision_id TEXT NOT NULL UNIQUE REFERENCES revision_record(revision_id),
            row_count INTEGER NOT NULL,
            missing_count INTEGER NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS station_rejection (
            rejection_no INTEGER PRIMARY KEY,
            batch_id TEXT,
            reason TEXT NOT NULL
        )
    ''')


def read_submission(db: sqlite3.Connection, batch_id: str) -> StoredSubmission | None:
    record = db.execute('''
        SELECT station, day, fingerprint, original_rows, revision_id, row_count, missing_count
        FROM station_submission WHERE batch_id = ?
    ''', (batch_id,)).fetchone()
    if record is None:
        return None
    station, day, fingerprint, payload, revision_id, row_count, missing_count = record
    batch = ValidatedBatch(batch_id, station, day, rows_from_data(load(payload)))
    receipt = SubmissionReceipt(batch_id, revision_id, row_count, missing_count)
    return StoredSubmission(batch, fingerprint, receipt)


def insert_submission(db: sqlite3.Connection, batch: ValidatedBatch,
                      fingerprint: str, receipt: SubmissionReceipt) -> None:
    db.execute('''
        INSERT INTO station_submission
            (batch_id, station, day, fingerprint, original_rows, revision_id, row_count, missing_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (batch.batch_id, batch.station, batch.day, fingerprint,
          dump([row_data(row) for row in batch.rows]), receipt.revision_id,
          receipt.row_count, receipt.missing_count))


def record_rejection(db: sqlite3.Connection, batch_id, reason: str) -> None:
    try:
        label = require_text(batch_id, 'batch ID')
    except ValueError:
        label = None
    db.execute('INSERT INTO station_rejection (batch_id, reason) VALUES (?, ?)', (label, reason))
