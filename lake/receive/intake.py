import sqlite3

from lake.issue.manifest import FrozenManifest, decode_manifest
from lake.issue.pages import PageIdentity
from lake.transactions import transaction
from lake.wire import require_text
from .inventory import IntakeReceipt, read_manifest, read_receipt, record_manifest, record_page
from .verify import verify_manifest, verify_page


def register_manifest(db: sqlite3.Connection, manifest: FrozenManifest | bytes) -> FrozenManifest:
    if isinstance(manifest, bytes):
        manifest = decode_manifest(manifest)
    verify_manifest(manifest)
    with transaction(db, write=True):
        try:
            previous = read_manifest(db, manifest.freeze_id)
        except KeyError:
            record_manifest(db, manifest)
            return manifest
        if previous != manifest:
            raise ValueError('freeze ID already binds a different manifest')
        return previous


def accept_page(db: sqlite3.Connection, target: FrozenManifest | bytes | str,
                identity: PageIdentity | None = None,
                payload: bytes | None = None) -> FrozenManifest | IntakeReceipt:
    """Register a directory, or verify and commit an exact page for a registered freeze."""
    if identity is None and payload is None:
        return register_manifest(db, target)
    freeze_id = require_text(target, 'freeze ID')
    if not isinstance(identity, PageIdentity) or type(payload) is not bytes:
        raise ValueError('page intake requires an exact identity and a bytes payload')
    with transaction(db, write=True):
        manifest = read_manifest(db, freeze_id)
        page = verify_page(manifest, identity, payload)
        previous = read_receipt(db, page.identity)
        if previous is not None:
            return previous
        receipt = IntakeReceipt(page.identity, 'intake:' + page.identity.digest)
        record_page(db, payload, receipt)
    return receipt
