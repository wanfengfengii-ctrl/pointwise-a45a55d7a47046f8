import json
import sqlite3

from lake import accept_page, amend, amend_move, audit_window, fetch_bundle, freeze_table, get_revision
from lake.issue.manifest import MoveEntry, decode_manifest, encode_manifest
from lake.reconcile.totals import WindowTotals
from lake.revision.ranges import KeyRange
from tests.support import LakeCase, readings


MOVE_BASE_ROWS = ((1, 5, 8), (5, 7, 9), (7, 9, 17), (12, 0, 31))


class MoveTests(LakeCase):
    def move_chain(self):
        base = self.submit_base(MOVE_BASE_ROWS, batch_id='move-morning-04').revision_id
        edit = amend(self.source, 'mark-missing', base, 2, 3, [(2, None, 21)])
        moved = amend_move(self.source, 'correct-key-band', edit, 1, 4, 5)
        return base, edit, moved

    def receive(self, cold, manifest, pages, *indices):
        accept_page(cold, encode_manifest(manifest))
        for index in indices:
            accept_page(cold, manifest.freeze_id, manifest.entries[index].identity, pages[index])

    def test_v9_move_source_account_and_parent_preserved(self):
        base, edit, moved = self.move_chain()
        self.assertEqual(moved, 'move:correct-key-band')
        self.assertEqual(readings(get_revision(self.source, moved)), ((5, 5), (6, None), (12, 0)))
        self.assertEqual(readings(get_revision(self.source, edit)),
                         ((1, 5), (2, None), (5, 7), (7, 9), (12, 0)))
        self.assertEqual(readings(get_revision(self.source, base)),
                         ((1, 5), (5, 7), (7, 9), (12, 0)))
        origins = get_revision(self.source, moved)
        self.assertEqual(tuple(row.origin.position for row in origins), (8, 21, 31))
        self.assertEqual(tuple(row.origin.kind for row in origins),
                         ('station', 'correction', 'station'))

    def test_v9_move_freeze_base_only_then_reopen_completion(self):
        _, _, moved = self.move_chain()
        _, manifest, pages = self.issue(moved, 'night-move')
        self.assertIsInstance(manifest.entries[2], MoveEntry)
        self.assertIsNone(pages[2])
        cold = self.open_cold()
        self.receive(cold, manifest, pages, 0)
        self.source.close()
        partial = audit_window(cold, manifest.freeze_id, 1, 8)
        self.assertEqual(readings(partial.rows), ((5, 5),))
        self.assertEqual(partial.verified_ranges, (KeyRange(1, 6), KeyRange(7, 8)))
        self.assertEqual(partial.pending_ranges, (KeyRange(6, 7),))
        self.assertIsNone(partial.totals)
        origin = partial.rows[0].origin
        self.assertEqual(origin.page, manifest.entries[0].identity)
        self.assertEqual(origin.page_position, 1)
        self.assertEqual(origin.source.position, 8)
        self.assertEqual(origin.source.kind, 'station')
        cold.close()
        cold = self.open_cold()
        accept_page(cold, manifest.freeze_id, manifest.entries[1].identity, pages[1])
        full = audit_window(cold, manifest.freeze_id, 1, 8)
        self.assertEqual(readings(full.rows), ((5, 5), (6, None)))
        self.assertEqual(full.verified_ranges, (KeyRange(1, 8),))
        self.assertEqual(full.pending_ranges, ())
        self.assertEqual(full.totals, WindowTotals(2, 1, 5))
        missing = full.rows[1].origin
        self.assertEqual(missing.page, manifest.entries[1].identity)
        self.assertEqual(missing.page_position, 1)
        self.assertEqual(missing.source.position, 21)
        self.assertEqual(missing.source.kind, 'correction')

    def test_v9_other_freeze_same_source_page_cannot_fill_gap(self):
        _, _, moved = self.move_chain()
        _, manifest, pages = self.issue(moved, 'move-handoff')
        _, other, other_pages = self.issue(moved, 'move-handoff-again')
        self.assertNotEqual(manifest.freeze_id, other.freeze_id)
        cold = self.open_cold()
        self.receive(cold, manifest, pages, 0)
        self.source.close()
        before = audit_window(cold, manifest.freeze_id, 1, 8)
        with self.assertRaises(ValueError):
            accept_page(cold, manifest.freeze_id, other.entries[1].identity, other_pages[1])
        after = audit_window(cold, manifest.freeze_id, 1, 8)
        self.assertEqual(after, before)
        self.assertEqual(after.pending_ranges, (KeyRange(6, 7),))

    def test_v9_later_edit_on_moved_revision(self):
        _, _, moved = self.move_chain()
        later = amend(self.source, 'restore-reading', moved, 6, 7, [(6, 11, 55)])
        self.assertEqual(readings(get_revision(self.source, later)), ((5, 5), (6, 11), (12, 0)))
        _, manifest, pages = self.issue(later, 'night-later')
        cold = self.open_cold()
        self.receive(cold, manifest, pages, 0, 3)
        self.source.close()
        result = audit_window(cold, manifest.freeze_id, 1, 8)
        self.assertEqual(readings(result.rows), ((5, 5), (6, 11)))
        self.assertEqual(result.verified_ranges, (KeyRange(1, 8),))
        self.assertEqual(result.pending_ranges, ())
        self.assertEqual(result.totals, WindowTotals(2, 0, 16))
        self.assertEqual(result.rows[1].origin.page, manifest.entries[3].identity)
        self.assertEqual(result.rows[1].origin.source.position, 55)

    def test_v9_second_move_relocates_band_again(self):
        _, _, moved = self.move_chain()
        second = amend_move(self.source, 'relocate-band-again', moved, 5, 8, 9)
        self.assertEqual(readings(get_revision(self.source, second)), ((9, 5), (10, None), (12, 0)))
        _, manifest, pages = self.issue(second, 'night-second')
        cold = self.open_cold()
        self.receive(cold, manifest, pages, 0)
        self.source.close()
        partial = audit_window(cold, manifest.freeze_id, 1, 12)
        self.assertEqual(readings(partial.rows), ((9, 5),))
        self.assertEqual(partial.pending_ranges, (KeyRange(10, 11),))
        self.assertIsNone(partial.totals)
        self.assertEqual(partial.rows[0].origin.page, manifest.entries[0].identity)
        self.assertEqual(partial.rows[0].origin.source.position, 8)
        accept_page(cold, manifest.freeze_id, manifest.entries[1].identity, pages[1])
        full = audit_window(cold, manifest.freeze_id, 1, 12)
        self.assertEqual(readings(full.rows), ((9, 5), (10, None)))
        self.assertEqual(full.totals, WindowTotals(2, 1, 5))
        self.assertEqual(full.rows[1].origin.page, manifest.entries[1].identity)
        self.assertEqual(full.rows[1].origin.source.position, 21)
        wider = audit_window(cold, manifest.freeze_id, 1, 13)
        self.assertEqual(readings(wider.rows), ((9, 5), (10, None), (12, 0)))
        self.assertEqual(wider.totals, WindowTotals(3, 1, 5))

    def test_v9_move_manifest_uses_v2_and_roundtrips(self):
        _, edit, moved = self.move_chain()
        _, move_manifest, _ = self.issue(moved, 'move-manifest')
        encoded = encode_manifest(move_manifest)
        self.assertEqual(json.loads(encoded.decode('ascii'))[0], 2)
        self.assertEqual(decode_manifest(encoded), move_manifest)
        _, plain_manifest, _ = self.issue(edit, 'plain-manifest')
        plain_encoded = encode_manifest(plain_manifest)
        self.assertEqual(json.loads(plain_encoded.decode('ascii'))[0], 1)
        self.assertEqual(decode_manifest(plain_encoded), plain_manifest)

    def test_v9_invalid_move_leaves_revision_ledger_unchanged(self):
        _, edit, moved = self.move_chain()
        before = self.source.execute('SELECT count(*) FROM revision_record').fetchone()
        for args in [(1, 4, 3), (1, 4, 2), (3, 3, 5), (4, 1, 6), (1, 4, '5'),
                     (1, 4, 5.0), (1, 4, True), (1.0, 4, 5), (False, 4, 5)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                amend_move(self.source, 'bad-move', edit, *args)
        for move_id in ('', '   ', None, 7):
            with self.subTest(move_id=move_id), self.assertRaises(ValueError):
                amend_move(self.source, move_id, edit, 1, 4, 5)
        with self.assertRaisesRegex(ValueError, 'already registered'):
            amend_move(self.source, 'correct-key-band', edit, 1, 4, 9)
        with self.assertRaises(KeyError):
            amend_move(self.source, 'unknown-parent', 'amend:absent', 1, 4, 5)
        self.assertEqual(self.source.execute('SELECT count(*) FROM revision_record').fetchone(), before)
        self.assertEqual(readings(get_revision(self.source, moved)), ((5, 5), (6, None), (12, 0)))
        with self.assertRaises(KeyError):
            get_revision(self.source, 'move:bad-move')

    def test_v9_adjacent_destination_allowed(self):
        _, edit, _ = self.move_chain()
        right = amend_move(self.source, 'shift-right-adjacent', edit, 1, 4, 4)
        self.assertEqual(readings(get_revision(self.source, right)),
                         ((4, 5), (5, None), (7, 9), (12, 0)))
        left = amend_move(self.source, 'shift-left-adjacent', edit, 1, 4, -2)
        self.assertEqual(readings(get_revision(self.source, left)),
                         ((-2, 5), (-1, None), (5, 7), (7, 9), (12, 0)))

    def test_v9_move_write_failure_is_retryable(self):
        _, edit, _ = self.move_chain()
        self.source.executescript('''
            CREATE TRIGGER reject_move AFTER INSERT ON revision_record
            WHEN NEW.revision_id LIKE 'move:%'
            BEGIN SELECT RAISE(ABORT, 'test move insertion failure'); END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'test move insertion failure'):
            amend_move(self.source, 'retry-move', edit, 1, 4, 5)
        with self.assertRaises(KeyError):
            get_revision(self.source, 'move:retry-move')
        self.source.execute('DROP TRIGGER reject_move')
        moved = amend_move(self.source, 'retry-move', edit, 1, 4, 5)
        self.assertEqual(readings(get_revision(self.source, moved)), ((5, 5), (6, None), (12, 0)))

    def test_v9_move_freeze_replay_and_rebind_conflict(self):
        _, edit, moved = self.move_chain()
        receipt, manifest, pages = self.issue(moved, 'move-issue')
        self.assertEqual(freeze_table(self.source, 'move-issue', moved), receipt)
        with self.assertRaisesRegex(ValueError, 'different revision'):
            freeze_table(self.source, 'move-issue', edit)
        self.assertEqual(fetch_bundle(self.source, receipt.freeze_id), manifest)
        cold = self.open_cold()
        self.assertEqual(accept_page(cold, manifest), manifest)
        self.assertEqual(accept_page(cold, encode_manifest(manifest)), manifest)
        with self.assertRaises(ValueError):
            accept_page(cold, manifest.freeze_id, manifest.entries[0].identity, pages[1])
        self.receive(cold, manifest, pages, 0)
        self.source.close()
        result = audit_window(cold, manifest.freeze_id, 1, 8)
        self.assertEqual(readings(result.rows), ((5, 5),))
        self.assertEqual(result.pending_ranges, (KeyRange(6, 7),))
