import sqlite3

from lake.issue.archive import init_archive
from lake.revision.ledger import register_base
from lake.revision.store import init_revision_store
from lake.transactions import enable_foreign_keys, transaction
from .store import SubmissionReceipt, init_station_store, insert_submission, read_submission, record_rejection
from .validation import batch_fingerprint, validate_batch


def initialize_source(db: sqlite3.Connection) -> None:
    """Initialize or reopen a source ledger and its archive on one connection."""
    enable_foreign_keys(db)
    with transaction(db, write=True):
        init_revision_store(db)
        init_station_store(db)
        init_archive(db)


def submit(db: sqlite3.Connection, batch_id: str, station: str, day: str, rows) -> SubmissionReceipt:
    """Post one station batch or reclaim the receipt for the exact same request."""
    try:
        batch = validate_batch(batch_id, station, day, rows)
    except ValueError as exc:
        with transaction(db, write=True):
            record_rejection(db, batch_id, str(exc))
        raise

    fingerprint = batch_fingerprint(batch)
    conflict = 'batch ID already binds a different request'
    with transaction(db, write=True):
        previous = read_submission(db, batch_id)
        if previous is None:
            base = register_base(db, batch)
            receipt = SubmissionReceipt(
                batch_id, base.revision_id, len(batch.rows),
                sum(row.liters is None for row in batch.rows),
            )
            insert_submission(db, batch, fingerprint, receipt)
            return receipt
        if previous.fingerprint == fingerprint and previous.batch == batch:
            return previous.receipt
        record_rejection(db, batch_id, conflict)
    raise ValueError(conflict)
