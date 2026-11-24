"""Transaction boundaries shared by the source ledger and the isolated store."""

from contextlib import contextmanager
import sqlite3


def enable_foreign_keys(db: sqlite3.Connection) -> None:
    if db.in_transaction:
        raise sqlite3.ProgrammingError('initialize outside an active transaction')
    db.execute('PRAGMA foreign_keys = ON')


@contextmanager
def transaction(db: sqlite3.Connection, *, write: bool):
    # Reserve the writer before checking idempotency, so a concurrent replay
    # sees either the original committed receipt or an available request ID.
    db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise
