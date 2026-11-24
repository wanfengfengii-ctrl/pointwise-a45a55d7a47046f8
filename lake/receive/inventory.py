from dataclasses import dataclass
import sqlite3

from lake.issue.manifest import FrozenManifest, decode_manifest, encode_manifest
from lake.issue.pages import ColdPage, PageIdentity, decode_page
from lake.wire import require_text


@dataclass(frozen=True)
class IntakeReceipt:
    identity: PageIdentity
    receipt_id: str


def init_inventory(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS cold_manifest (
            freeze_id TEXT PRIMARY KEY NOT NULL,
            manifest BLOB NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS cold_page (
            freeze_id TEXT NOT NULL REFERENCES cold_manifest(freeze_id),
            digest TEXT NOT NULL,
            payload BLOB NOT NULL,
            PRIMARY KEY (freeze_id, digest)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS cold_receipt (
            freeze_id TEXT NOT NULL,
            digest TEXT NOT NULL,
            receipt_id TEXT NOT NULL UNIQUE,
            PRIMARY KEY (freeze_id, digest),
            FOREIGN KEY (freeze_id, digest) REFERENCES cold_page(freeze_id, digest)
        )
    ''')


def record_manifest(db: sqlite3.Connection, manifest: FrozenManifest) -> None:
    db.execute('INSERT INTO cold_manifest (freeze_id, manifest) VALUES (?, ?)',
               (manifest.freeze_id, encode_manifest(manifest)))


def record_page(db: sqlite3.Connection, payload: bytes, receipt: IntakeReceipt) -> None:
    """Write a verified page and its receipt in the same caller-owned transaction."""
    identity = receipt.identity
    db.execute('INSERT INTO cold_page (freeze_id, digest, payload) VALUES (?, ?, ?)',
               (identity.freeze_id, identity.digest, payload))
    db.execute('INSERT INTO cold_receipt (freeze_id, digest, receipt_id) VALUES (?, ?, ?)',
               (identity.freeze_id, identity.digest, receipt.receipt_id))


def read_manifest(db: sqlite3.Connection, freeze_id: str) -> FrozenManifest:
    require_text(freeze_id, 'freeze ID')
    record = db.execute('SELECT manifest FROM cold_manifest WHERE freeze_id = ?', (freeze_id,)).fetchone()
    if record is None:
        raise KeyError(f'unknown received freeze {freeze_id!r}')
    return decode_manifest(record[0])


def read_received_pages(db: sqlite3.Connection, freeze_id: str) -> dict[PageIdentity, ColdPage]:
    records = db.execute('SELECT payload FROM cold_page WHERE freeze_id = ?', (freeze_id,))
    pages = {}
    for (payload,) in records:
        page = decode_page(payload)
        pages[page.identity] = page
    return pages


def read_receipt(db: sqlite3.Connection, identity: PageIdentity) -> IntakeReceipt | None:
    record = db.execute('''
        SELECT r.receipt_id, p.payload
        FROM cold_receipt AS r JOIN cold_page AS p USING (freeze_id, digest)
        WHERE r.freeze_id = ? AND r.digest = ?
    ''', (identity.freeze_id, identity.digest)).fetchone()
    if record is None or decode_page(record[1]).identity != identity:
        return None
    return IntakeReceipt(identity, record[0])
