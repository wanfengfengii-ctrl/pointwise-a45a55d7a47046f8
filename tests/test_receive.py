from dataclasses import replace
import sqlite3

from lake import accept_page, amend, audit_window
from lake.issue.pages import decode_page
from lake.receive.inventory import read_receipt
from lake.receive.reopen import read_inventory_snapshot
from lake.reconcile.totals import WindowTotals
from lake.revision.ranges import KeyRange
from tests.support import LakeCase, readings


class ReceiveTests(LakeCase):
    def partial_bundle(self):
        base, edit, clear = self.chain()
        _, manifest, pages = self.issue(clear, 'original')
        cold = self.open_cold()
        self.assertEqual(accept_page(cold, manifest), manifest)
        self.assertFalse(read_inventory_snapshot(cold, manifest.freeze_id).pages)
        for index in (0, 2):
            accept_page(cold, manifest.freeze_id, manifest.entries[index].identity, pages[index])
        return base, edit, manifest, pages, cold

    def test_v7_wrong_revision_leaves_gap_then_exact_page_completes(self):
        base, edit, manifest, pages, cold = self.partial_bundle()
        sibling = amend(self.source, 'other-edit', base, 1, 3, [(2, 13, 21)])
        _, other, other_pages = self.issue(sibling, 'wrong-freeze')
        _, reissued, reissued_pages = self.issue(edit, 'same-revision-other-freeze')
        wanted = manifest.entries[1].identity
        initial = audit_window(cold, manifest.freeze_id, 1, 4)
        self.assertEqual(initial.pending_ranges, (KeyRange(1, 2),))
        self.assertEqual(readings(initial.rows), ((3, 11),))
        self.assertIsNone(initial.totals)
        self.assertEqual(readings(decode_page(other_pages[1]).rows), readings(decode_page(pages[1]).rows))
        self.assertEqual(decode_page(reissued_pages[1]).rows, decode_page(pages[1]).rows)
        for identity, payload in ((other.entries[1].identity, other_pages[1]),
                                  (reissued.entries[1].identity, reissued_pages[1]),
                                  (wanted, other_pages[1])):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                accept_page(cold, manifest.freeze_id, identity, payload)
            self.assertIsNone(read_receipt(cold, wanted))
            self.assertEqual(audit_window(cold, manifest.freeze_id, 1, 4), initial)
        self.assertEqual(accept_page(cold, manifest.freeze_id, wanted, pages[1]).identity, wanted)
        full = audit_window(cold, manifest.freeze_id, 1, 4)
        self.assertEqual(full.rows, initial.rows)
        self.assertEqual(full.verified_ranges, (KeyRange(1, 4),))
        self.assertEqual(full.pending_ranges, ())
        self.assertEqual(full.totals, WindowTotals(1, 0, 11))

    def test_v7_damaged_body_rejected_before_and_after_exact_intake(self):
        _, _, manifest, pages, cold = self.partial_bundle()
        freeze_id = manifest.freeze_id
        identity = manifest.entries[1].identity
        before = audit_window(cold, freeze_id, 1, 4)
        damaged = pages[1] + b' '
        with self.assertRaises(ValueError):
            accept_page(cold, freeze_id, identity, damaged)
        self.assertIsNone(read_receipt(cold, identity))
        self.assertEqual(audit_window(cold, freeze_id, 1, 4), before)
        receipt = accept_page(cold, freeze_id, identity, pages[1])
        with self.assertRaises(ValueError):
            accept_page(cold, freeze_id, identity, damaged)
        self.assertEqual(read_receipt(cold, identity), receipt)
        self.assertEqual(audit_window(cold, freeze_id, 1, 4).totals, WindowTotals(1, 0, 11))

    def test_invalid_and_conflicting_manifest_leave_inventory_unchanged(self):
        _, _, manifest, _, cold = self.partial_bundle()
        before = read_inventory_snapshot(cold, manifest.freeze_id)
        bad_sequence = replace(manifest, entries=tuple(reversed(manifest.entries)))
        for invalid in (bad_sequence, b'{}', replace(manifest, station='Other station')):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                accept_page(cold, invalid)
        self.assertEqual(accept_page(cold, manifest), manifest)
        self.assertEqual(read_inventory_snapshot(cold, manifest.freeze_id), before)

    def test_v8_failed_commit_reopen_retry_and_reclaim(self):
        _, _, manifest, pages, cold = self.partial_bundle()
        freeze_id = manifest.freeze_id
        identity = manifest.entries[1].identity
        before = audit_window(cold, freeze_id, 1, 4)
        self.assertEqual(before.pending_ranges, (KeyRange(1, 2),))
        # The deferred foreign key fires at COMMIT after both production inserts.
        cold.executescript('''
            CREATE TABLE test_commit_parent (id INTEGER PRIMARY KEY);
            CREATE TABLE test_commit_child (
                id INTEGER REFERENCES test_commit_parent(id) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER test_fail_receipt_commit AFTER INSERT ON cold_receipt
            BEGIN INSERT INTO test_commit_child VALUES (1); END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY'):
            accept_page(cold, freeze_id, identity, pages[1])
        self.assertFalse(cold.in_transaction)
        self.assertIsNone(read_receipt(cold, identity))
        cold.close()
        cold = self.open_cold()
        self.assertEqual(audit_window(cold, freeze_id, 1, 4), before)
        self.assertNotIn(identity, read_inventory_snapshot(cold, freeze_id).pages)
        self.assertIsNone(read_receipt(cold, identity))
        cold.execute('DROP TRIGGER test_fail_receipt_commit')
        receipt = accept_page(cold, freeze_id, identity, pages[1])
        self.assertEqual(audit_window(cold, freeze_id, 1, 4).totals, WindowTotals(1, 0, 11))
        cold.close()
        cold = self.open_cold()
        self.assertEqual(accept_page(cold, freeze_id, identity, pages[1]), receipt)
        self.assertEqual(read_receipt(cold, identity), receipt)
        reopened = audit_window(cold, freeze_id, 1, 4)
        self.assertEqual(reopened.pending_ranges, ())
        self.assertEqual(reopened.rows, before.rows)
        self.assertEqual(reopened.totals, WindowTotals(1, 0, 11))
