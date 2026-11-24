from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from lake import amend, fetch_bundle, freeze_table, initialize_source, open_inventory, read_page, submit


BASE_ROWS = ((1, 5, 8), (2, 7, 9), (3, 11, 17))


class LakeCase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.source_path = root / 'source.sqlite'
        self.cold_path = root / 'cold.sqlite'
        self.source = self.open_source()

    def open_source(self):
        db = sqlite3.connect(self.source_path)
        self.addCleanup(db.close)
        initialize_source(db)
        return db

    def open_cold(self):
        db = open_inventory(self.cold_path)
        self.addCleanup(db.close)
        return db

    def submit_base(self, rows=BASE_ROWS, batch_id='station-b1'):
        return submit(self.source, batch_id, 'Qinglan-04', '2026-08-12', rows)

    def chain(self):
        base = self.submit_base().revision_id
        edit = amend(self.source, 'replace-b', base, 1, 3, [(2, 13, 21)])
        clear = amend(self.source, 'clear-b', edit, 2, 3, [])
        return base, edit, clear

    def issue(self, revision_id, request_id):
        receipt = freeze_table(self.source, request_id, revision_id)
        manifest = fetch_bundle(self.source, receipt.freeze_id)
        pages = tuple(read_page(self.source, entry.identity) for entry in manifest.entries)
        return receipt, manifest, pages


def readings(rows):
    return tuple((row.key, row.liters) for row in rows)
