import sqlite3

from lake.ingest.rows import order_rows_by_key
from lake.ingest.validation import ValidatedBatch
from lake.transactions import transaction
from lake.wire import require_text
from .apply import validate_replacement
from .ranges import validate_range
from .store import RevisionRecord, insert_revision, read_revision


def register_base(db: sqlite3.Connection, batch: ValidatedBatch) -> RevisionRecord:
    """Write the base inside the caller's station submission transaction."""
    base = RevisionRecord(
        'batch:' + batch.batch_id, None, batch.station, batch.day, None,
        order_rows_by_key(batch.rows),
    )
    insert_revision(db, base)
    return base


def amend(db: sqlite3.Connection, correction_id: str, parent_id: str,
          lo: int, hi: int, rows) -> str:
    """Post a new immutable correction to the named parent revision."""
    require_text(correction_id, 'correction ID')
    require_text(parent_id, 'parent revision ID')
    span = validate_range(lo, hi)
    replacement = validate_replacement(correction_id, span, rows)
    revision_id = 'amend:' + correction_id
    with transaction(db, write=True):
        parent = read_revision(db, parent_id)
        try:
            read_revision(db, revision_id)
        except KeyError:
            pass
        else:
            raise ValueError('correction ID is already registered')
        insert_revision(db, RevisionRecord(
            revision_id, parent_id, parent.station, parent.day, span, replacement,
        ))
    return revision_id
