import sqlite3

from lake import accept_page, amend, audit_window, fetch_bundle, freeze_table, get_revision, initialize_source, read_page
from lake.issue.archive import read_issue_receipt
from lake.issue.manifest import decode_manifest, encode_manifest
from lake.issue.pages import decode_page
from lake.revision.ranges import KeyRange
from tests.support import LakeCase, readings


class FreezeTests(LakeCase):
    def test_v3_three_versions_and_source_reinitialization(self):
        versions = self.chain()
        expected = (((1, 5), (2, 7), (3, 11)), ((2, 13), (3, 11)), ((3, 11),))
        issued = tuple(self.issue(version, f'issue-{index}') for index, version in enumerate(versions))
        initialize_source(self.source)
        self.source.close()
        self.source = self.open_source()
        cold = self.open_cold()
        for version, values, (receipt, manifest, pages) in zip(versions, expected, issued, strict=True):
            with self.subTest(version=version):
                self.assertEqual(readings(get_revision(self.source, version)), values)
                self.assertEqual(fetch_bundle(self.source, receipt.freeze_id), manifest)
                accept_page(cold, manifest)
                for entry, payload in zip(manifest.entries, pages, strict=True):
                    accept_page(cold, manifest.freeze_id, entry.identity, payload)
                result = audit_window(cold, manifest.freeze_id, 1, 4)
                self.assertEqual(readings(result.rows), values)
        middle_manifest = issued[1][1]
        middle = audit_window(cold, middle_manifest.freeze_id, 2, 4)
        self.assertEqual(middle.rows[0].origin.page, middle_manifest.entries[1].identity)
        self.assertEqual(middle.rows[0].origin.source.position, 21)
        self.assertEqual(middle.rows[1].origin.page, middle_manifest.entries[0].identity)
        self.assertEqual(readings(audit_window(cold, middle_manifest.freeze_id, 1, 3).rows), ((2, 13),))

    def test_v3_manifest_declarations(self):
        base, edit, clear = self.chain()
        receipt, manifest, pages = self.issue(clear, 'night')
        self.assertEqual(manifest.entries[0].coverage, KeyRange(1, 4))
        self.assertEqual(manifest.entries[1].coverage, KeyRange(1, 3))
        self.assertEqual(manifest.entries[2].coverage, KeyRange(2, 3))
        self.assertEqual(tuple(e.identity.revision_id for e in manifest.entries), (base, edit, clear))
        self.assertEqual(tuple(e.identity.page_no for e in manifest.entries), (1, 2, 3))
        parsed = tuple(decode_page(payload) for payload in pages)
        self.assertEqual(tuple(p.identity for p in parsed), tuple(e.identity for e in manifest.entries))
        self.assertTrue(all(p.identity.freeze_id == receipt.freeze_id for p in parsed))
        self.assertEqual(readings(parsed[1].rows), ((2, 13),))
        self.assertEqual(parsed[2].rows, ())
        self.assertEqual(decode_manifest(encode_manifest(manifest)), manifest)

    def test_v3_issue_request_replay_and_conflict(self):
        base, edit, unused_clear = self.chain()
        receipt, manifest, pages = self.issue(base, 'issue-key')
        self.assertEqual(freeze_table(self.source, 'issue-key', base), receipt)
        with self.assertRaisesRegex(ValueError, 'different revision'):
            freeze_table(self.source, 'issue-key', edit)
        self.assertEqual(read_issue_receipt(self.source, 'issue-key'), receipt)
        self.assertEqual(fetch_bundle(self.source, receipt.freeze_id), manifest)
        self.assertEqual(read_page(self.source, manifest.entries[0].identity), pages[0])
        self.assertEqual(self.source.execute('SELECT count(*) FROM issue_bundle').fetchone(), (1,))

    def test_v3_reclaim_original_in_reverse_issuance_order(self):
        versions = self.chain()
        archived = tuple(self.issue(version, f'order-{index}') for index, version in enumerate(versions))
        for receipt, original, pages in reversed(archived):
            restored = fetch_bundle(self.source, receipt.freeze_id)
            self.assertEqual(restored, original)
            self.assertEqual(tuple(read_page(self.source, p.identity) for p in restored.entries), pages)
        self.assertEqual(readings(decode_page(archived[0][2][0]).rows), ((1, 5), (2, 7), (3, 11)))

    def test_v4_right_endpoint_rejected(self):
        base = self.submit_base().revision_id
        receipt, manifest, _ = self.issue(base, 'before-invalid')
        with self.assertRaisesRegex(ValueError, 'outside'):
            amend(self.source, 'bad-end', base, 1, 3, [(3, 99, 30)])
        self.assertEqual(fetch_bundle(self.source, receipt.freeze_id), manifest)
        self.assertEqual(readings(get_revision(self.source, base)), ((1, 5), (2, 7), (3, 11)))
        with self.assertRaises(KeyError):
            get_revision(self.source, 'amend:bad-end')

    def test_v4_unknown_parent_leaves_source_and_archive_unchanged(self):
        base = self.submit_base().revision_id
        receipt, manifest, _ = self.issue(base, 'before-unknown')
        with self.assertRaises(KeyError):
            amend(self.source, 'unknown-parent', 'amend:absent', 1, 3, [(2, 40, 1)])
        with self.assertRaises(KeyError):
            freeze_table(self.source, 'cannot-issue', 'amend:unknown-parent')
        with self.assertRaises(KeyError):
            fetch_bundle(self.source, 'freeze:unknown')
        self.assertEqual(readings(get_revision(self.source, base)), ((1, 5), (2, 7), (3, 11)))
        self.assertEqual(fetch_bundle(self.source, receipt.freeze_id), manifest)
        self.assertEqual(self.source.execute('SELECT count(*) FROM revision_record').fetchone(), (1,))
        self.assertEqual(self.source.execute('SELECT count(*) FROM issue_bundle').fetchone(), (1,))

    def test_revision_and_archive_write_failures_are_retryable(self):
        base = self.submit_base().revision_id
        self.source.executescript('''
            CREATE TRIGGER reject_edit AFTER INSERT ON revision_record WHEN NEW.parent_id IS NOT NULL
            BEGIN SELECT RAISE(ABORT, 'test revision insertion failure'); END;
            CREATE TRIGGER reject_archive AFTER INSERT ON issue_page
            BEGIN SELECT RAISE(ABORT, 'test archive insertion failure'); END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'test revision insertion failure'):
            amend(self.source, 'retry-edit', base, 2, 3, [])
        with self.assertRaises(KeyError):
            get_revision(self.source, 'amend:retry-edit')
        self.source.execute('DROP TRIGGER reject_edit')
        edit = amend(self.source, 'retry-edit', base, 2, 3, [])
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'test archive insertion failure'):
            freeze_table(self.source, 'retry-issue', edit)
        self.assertIsNone(read_issue_receipt(self.source, 'retry-issue'))
        self.assertEqual(self.source.execute('SELECT count(*) FROM issue_bundle').fetchone(), (0,))
        self.assertEqual(self.source.execute('SELECT count(*) FROM issue_page').fetchone(), (0,))
        self.source.execute('DROP TRIGGER reject_archive')
        receipt = freeze_table(self.source, 'retry-issue', edit)
        self.assertEqual(fetch_bundle(self.source, receipt.freeze_id).revision_id, edit)
