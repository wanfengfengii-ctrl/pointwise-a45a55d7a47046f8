import sqlite3

from lake.ingest.rows import order_rows_by_key
from lake.ingest.validation import ValidatedBatch
from lake.transactions import transaction
from lake.wire import require_text
from .apply import materialize_revision, moved_rows, validate_replacement
from .history import read_lineage
from .ranges import validate_move, validate_range
from .store import RevisionRecord, insert_revision, read_revision


def register_base(db: sqlite3.Connection, batch: ValidatedBatch) -> RevisionRecord:
    """Write the base inside the caller's station submission transaction."""
    base = RevisionRecord(
        'batch:' + batch.batch_id, None, batch.station, batch.day, None,
        order_rows_by_key(batch.rows),
    )
    insert_revision(db, base)
    return base


def _check_fresh(db: sqlite3.Connection, revision_id: str, taken: str) -> None:
    try:
        read_revision(db, revision_id)
    except KeyError:
        return
    raise ValueError(taken)


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
        _check_fresh(db, revision_id, 'correction ID is already registered')
        insert_revision(db, RevisionRecord(
            revision_id, parent_id, parent.station, parent.day, span, replacement,
        ))
    return revision_id


def amend_move(db: sqlite3.Connection, move_id: str, parent_id: str,
               lo: int, hi: int, dest_lo: int) -> str:
    """Relocate the parent's whole source band [lo, hi) to start at dest_lo."""
    require_text(move_id, 'move ID')
    require_text(parent_id, 'parent revision ID')
    move = validate_move(lo, hi, dest_lo)
    revision_id = 'move:' + move_id
    with transaction(db, write=True):
        parent = read_revision(db, parent_id)
        _check_fresh(db, revision_id, 'move ID is already registered')
        parent_rows = materialize_revision(read_lineage(db, parent_id))
        insert_revision(db, RevisionRecord(
            revision_id, parent_id, parent.station, parent.day, move,
            moved_rows(parent_rows, move),
        ))
    return revision_id
