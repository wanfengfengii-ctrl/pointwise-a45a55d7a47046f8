import sqlite3

from lake.ingest.rows import ReadingRow
from lake.wire import require_text
from .apply import materialize_revision
from .store import RevisionRecord, read_revision


def read_lineage(db: sqlite3.Connection, revision_id: str) -> tuple[RevisionRecord, ...]:
    require_text(revision_id, 'revision ID')
    lineage = []
    seen = set()
    current = revision_id
    while current is not None:
        if current in seen:
            raise ValueError('cyclic revision lineage')
        seen.add(current)
        record = read_revision(db, current)
        lineage.append(record)
        current = record.parent_id
    return tuple(reversed(lineage))


def get_revision(db: sqlite3.Connection, revision_id: str) -> tuple[ReadingRow, ...]:
    """Read the named revision in integer-key order and retain original sources."""
    return materialize_revision(read_lineage(db, revision_id))
