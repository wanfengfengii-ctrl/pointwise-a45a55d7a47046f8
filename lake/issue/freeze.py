from hashlib import sha256
import sqlite3

from lake.ingest.rows import row_data
from lake.revision.history import read_lineage
from lake.revision.ranges import range_data
from lake.revision.store import RevisionRecord
from lake.transactions import transaction
from lake.wire import dump, require_text
from .archive import commit_bundle, read_bundle, read_issue_receipt
from .manifest import FrozenManifest, build_manifest
from .pages import make_cold_page
from .receipts import IssueReceipt, make_issue_receipt, match_issue_request


def _freeze_id(request_id: str, lineage: tuple[RevisionRecord, ...]) -> str:
    records = [
        [record.revision_id, record.parent_id, range_data(record.declaration),
         [row_data(row) for row in record.rows]]
        for record in lineage
    ]
    base = lineage[0]
    facts = dump([1, request_id, base.station, base.day, records])
    return 'freeze:' + sha256(facts).hexdigest()


def freeze_table(db: sqlite3.Connection, request_id: str, revision_id: str) -> IssueReceipt:
    """Issue the named formal revision or return the receipt of its original issuance."""
    require_text(request_id, 'issue request ID')
    require_text(revision_id, 'revision ID')
    with transaction(db, write=True):
        previous = read_issue_receipt(db, request_id)
        if previous is not None:
            return match_issue_request(previous, revision_id)
        lineage = read_lineage(db, revision_id)
        freeze_id = _freeze_id(request_id, lineage)
        pages = tuple(
            make_cold_page(freeze_id, record.revision_id, page_no, record.rows)
            for page_no, record in enumerate(lineage, start=1)
        )
        manifest = build_manifest(freeze_id, lineage, pages)
        receipt = make_issue_receipt(request_id, revision_id, freeze_id)
        commit_bundle(db, manifest, pages, receipt)
    return receipt


def fetch_bundle(db: sqlite3.Connection, freeze_id: str) -> FrozenManifest:
    """Reclaim the unchanged directory of a previously issued freeze."""
    return read_bundle(db, freeze_id)
