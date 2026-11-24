import sqlite3

from lake.wire import require_text
from .manifest import FrozenManifest, decode_manifest, encode_manifest
from .pages import ColdPage, PageIdentity, decode_page, encode_page
from .receipts import IssueReceipt


def init_archive(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS issue_bundle (
            freeze_id TEXT PRIMARY KEY NOT NULL,
            manifest BLOB NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS issue_page (
            freeze_id TEXT NOT NULL REFERENCES issue_bundle(freeze_id),
            digest TEXT NOT NULL,
            payload BLOB NOT NULL,
            PRIMARY KEY (freeze_id, digest)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS issue_receipt (
            request_id TEXT PRIMARY KEY NOT NULL,
            revision_id TEXT NOT NULL REFERENCES revision_record(revision_id),
            freeze_id TEXT NOT NULL UNIQUE REFERENCES issue_bundle(freeze_id)
        )
    ''')


def commit_bundle(db: sqlite3.Connection, manifest: FrozenManifest,
                  pages: tuple[ColdPage, ...], receipt: IssueReceipt) -> None:
    """Store an assembled issuance inside the caller's archive transaction."""
    db.execute('INSERT INTO issue_bundle (freeze_id, manifest) VALUES (?, ?)',
               (manifest.freeze_id, encode_manifest(manifest)))
    db.executemany('INSERT INTO issue_page (freeze_id, digest, payload) VALUES (?, ?, ?)', (
        (manifest.freeze_id, page.identity.digest, encode_page(page)) for page in pages
    ))
    db.execute('INSERT INTO issue_receipt (request_id, revision_id, freeze_id) VALUES (?, ?, ?)',
               (receipt.request_id, receipt.revision_id, receipt.freeze_id))


def read_bundle(db: sqlite3.Connection, freeze_id: str) -> FrozenManifest:
    require_text(freeze_id, 'freeze ID')
    record = db.execute('SELECT manifest FROM issue_bundle WHERE freeze_id = ?', (freeze_id,)).fetchone()
    if record is None:
        raise KeyError(f'unknown archived freeze {freeze_id!r}')
    return decode_manifest(record[0])


def read_page(db: sqlite3.Connection, identity: PageIdentity) -> bytes:
    record = db.execute('SELECT payload FROM issue_page WHERE freeze_id = ? AND digest = ?',
                        (identity.freeze_id, identity.digest)).fetchone()
    if record is None or decode_page(record[0]).identity != identity:
        raise KeyError('unknown archived cold page identity')
    return record[0]


def read_issue_receipt(db: sqlite3.Connection, request_id: str) -> IssueReceipt | None:
    record = db.execute('SELECT revision_id, freeze_id FROM issue_receipt WHERE request_id = ?',
                        (request_id,)).fetchone()
    if record is None:
        return None
    return IssueReceipt(request_id, *record)
