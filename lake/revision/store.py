from dataclasses import dataclass
import sqlite3

from lake.ingest.rows import ReadingRow, row_data, rows_from_data
from lake.wire import dump, load
from .ranges import KeyMove, KeyRange, range_data, range_from_data


@dataclass(frozen=True)
class RevisionRecord:
    revision_id: str
    parent_id: str | None
    station: str
    day: str
    declaration: KeyRange | KeyMove | None
    rows: tuple[ReadingRow, ...]


def init_revision_store(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS revision_record (
            revision_id TEXT PRIMARY KEY NOT NULL,
            parent_id TEXT REFERENCES revision_record(revision_id),
            station TEXT NOT NULL,
            day TEXT NOT NULL,
            declaration BLOB,
            readings BLOB NOT NULL,
            CHECK ((parent_id IS NULL) = (declaration IS NULL))
        )
    ''')


def read_revision(db: sqlite3.Connection, revision_id: str) -> RevisionRecord:
    record = db.execute('''
        SELECT parent_id, station, day, declaration, readings
        FROM revision_record WHERE revision_id = ?
    ''', (revision_id,)).fetchone()
    if record is None:
        raise KeyError(f'unknown revision {revision_id!r}')
    parent, station, day, declaration, readings = record
    span = None if declaration is None else range_from_data(load(declaration))
    return RevisionRecord(revision_id, parent, station, day, span, rows_from_data(load(readings)))


def insert_revision(db: sqlite3.Connection, record: RevisionRecord) -> None:
    declaration = None if record.declaration is None else dump(range_data(record.declaration))
    db.execute('''
        INSERT INTO revision_record (revision_id, parent_id, station, day, declaration, readings)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (record.revision_id, record.parent_id, record.station, record.day,
          declaration, dump([row_data(row) for row in record.rows])))
