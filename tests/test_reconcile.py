from lake import accept_page, amend, audit_window
from lake.issue.manifest import encode_manifest
from lake.reconcile.totals import WindowTotals
from lake.revision.ranges import KeyRange
from tests.support import LakeCase, readings


class ReconcileTests(LakeCase):
    def receive(self, cold, manifest, pages, *indices):
        accept_page(cold, encode_manifest(manifest))
        for index in indices:
            accept_page(cold, manifest.freeze_id, manifest.entries[index].identity, pages[index])

    def test_v5_offline_old_freeze_after_new_correction_and_reopen(self):
        source_rows = ((1, 0, 4), (2, None, 6), (3, 11, 17))
        base = self.submit_base(source_rows).revision_id
        _, manifest, pages = self.issue(base, 'issued-base')
        cold = self.open_cold()
        self.receive(cold, manifest, pages, 0)
        self.source.close()
        original = audit_window(cold, manifest.freeze_id, 1, 4)
        self.assertEqual(readings(original.rows), ((1, 0), (2, None), (3, 11)))
        self.assertEqual(original.totals, WindowTotals(3, 1, 11))
        self.assertEqual(original.verified_ranges, (KeyRange(1, 4),))
        self.assertEqual(original.pending_ranges, ())
        self.source = self.open_source()
        newer = amend(self.source, 'late', base, 1, 4, [(2, 99, 1)])
        _, other, other_pages = self.issue(newer, 'issued-newer')
        self.receive(cold, other, other_pages, 0, 1)
        self.source.close()
        cold.close()
        cold = self.open_cold()
        self.assertEqual(audit_window(cold, manifest.freeze_id, 1, 4), original)
        self.assertEqual(readings(audit_window(cold, other.freeze_id, 1, 4).rows), ((2, 99),))

    def test_v5_origin_position_survives_sort_window_and_reopen(self):
        base = self.submit_base(((3, 11, 17), (1, 5, 8), (2, 7, 9))).revision_id
        _, manifest, pages = self.issue(base, 'origin')
        cold = self.open_cold()
        self.receive(cold, manifest, pages, 0)
        self.source.close()
        full = audit_window(cold, manifest.freeze_id, 1, 4)
        narrow = audit_window(cold, manifest.freeze_id, 3, 4)
        self.assertEqual(narrow.rows, (full.rows[2],))
        origin = narrow.rows[0].origin
        self.assertEqual(origin.source.position, 17)
        self.assertEqual(origin.source.kind, 'station')
        self.assertEqual(origin.source.source_id, 'station-b1')
        self.assertEqual(origin.page, manifest.entries[0].identity)
        self.assertEqual(origin.page_position, 3)
        self.assertEqual(origin.freeze_id, manifest.freeze_id)
        cold.close()
        self.assertEqual(audit_window(self.open_cold(), manifest.freeze_id, 3, 4), narrow)

    def test_v5_exact_metrics(self):
        base = self.submit_base(((1, 0, 2), (2, None, 4), (3, 9007199254740993, 17))).revision_id
        _, manifest, pages = self.issue(base, 'large-reading')
        cold = self.open_cold()
        self.receive(cold, manifest, pages, 0)
        self.source.close()
        result = audit_window(cold, manifest.freeze_id, 1, 4)
        self.assertEqual(readings(result.rows), ((1, 0), (2, None), (3, 9007199254740993)))
        self.assertEqual(result.totals, WindowTotals(3, 1, 9007199254740993))
        self.assertEqual(result.verified_ranges, (KeyRange(1, 4),))

    def test_v5_integer_storage_beyond_decimal_conversion_limit(self):
        large = 1 << 20000
        base = self.submit_base(((large, large, 0), (large + 1, -large + 7, 1))).revision_id
        _, manifest, pages = self.issue(base, 'large-keys')
        cold = self.open_cold()
        self.receive(cold, manifest, pages, 0)
        result = audit_window(cold, manifest.freeze_id, large, large + 2)
        self.assertEqual(readings(result.rows), ((large, large), (large + 1, -large + 7)))
        self.assertEqual(result.totals, WindowTotals(2, 0, 7))

    def test_v5_invalid_window_and_unknown_freeze_preserve_inventory(self):
        base = self.submit_base().revision_id
        _, manifest, pages = self.issue(base, 'invalid-window')
        cold = self.open_cold()
        self.receive(cold, manifest, pages, 0)
        original = audit_window(cold, manifest.freeze_id, 1, 4)
        for lo, hi in [(4, 1), (2, 2), (False, 4), (1, 4.0), ('1', 4)]:
            with self.subTest(lo=lo, hi=hi), self.assertRaises(ValueError):
                audit_window(cold, manifest.freeze_id, lo, hi)
        with self.assertRaises(KeyError):
            audit_window(cold, 'freeze:absent', 1, 4)
        self.assertEqual(audit_window(cold, manifest.freeze_id, 1, 4), original)
        self.assertEqual(cold.execute('SELECT count(*) FROM cold_receipt').fetchone(), (1,))

    def test_v6_later_empty_page_shadows_missing_page(self):
        _, _, clear = self.chain()
        _, manifest, pages = self.issue(clear, 'partial')
        cold = self.open_cold()
        self.receive(cold, manifest, pages, 0, 2)
        small = audit_window(cold, manifest.freeze_id, 2, 3)
        self.assertEqual(small.rows, ())
        self.assertEqual(small.verified_ranges, (KeyRange(2, 3),))
        self.assertEqual(small.pending_ranges, ())
        self.assertEqual(small.totals, WindowTotals(0, 0, 0))
        large = audit_window(cold, manifest.freeze_id, 1, 4)
        self.assertEqual(readings(large.rows), ((3, 11),))
        self.assertEqual(large.rows[0].origin.page, manifest.entries[0].identity)
        self.assertEqual(large.verified_ranges, (KeyRange(2, 4),))
        self.assertEqual(large.pending_ranges, (KeyRange(1, 2),))
        self.assertIsNone(large.totals)

    def test_v6_same_rows_different_range(self):
        # Separate source ledgers preserve exactly the same correction IDs and row origins.
        cold = self.open_cold()
        results = []
        for declaration_lo in (1, 2):
            self.source_path = self.source_path.with_name(f'branch-{declaration_lo}.sqlite')
            self.source = self.open_source()
            base = self.submit_base().revision_id
            edit = amend(self.source, 'replace-b', base, declaration_lo, 3, [(2, 13, 21)])
            clear = amend(self.source, 'clear-b', edit, 2, 3, [])
            _, manifest, pages = self.issue(clear, 'paired')
            self.receive(cold, manifest, pages, 0, 2)
            small = audit_window(cold, manifest.freeze_id, 2, 3)
            self.assertEqual(small.rows, ())
            self.assertEqual(small.totals, WindowTotals(0, 0, 0))
            results.append(audit_window(cold, manifest.freeze_id, 1, 4))
        wide, narrow = results
        self.assertEqual(readings(wide.rows), ((3, 11),))
        self.assertEqual(wide.pending_ranges, (KeyRange(1, 2),))
        self.assertIsNone(wide.totals)
        self.assertEqual(readings(narrow.rows), ((1, 5), (3, 11)))
        self.assertEqual(narrow.pending_ranges, ())
        self.assertEqual(narrow.verified_ranges, (KeyRange(1, 4),))
        self.assertEqual(narrow.totals, WindowTotals(2, 0, 16))

    def test_v6_empty_page_pending_until_received(self):
        _, _, clear = self.chain()
        _, manifest, pages = self.issue(clear, 'empty-pending')
        cold = self.open_cold()
        self.receive(cold, manifest, pages, 0, 1)
        pending = audit_window(cold, manifest.freeze_id, 2, 3)
        self.assertEqual(pending.rows, ())
        self.assertEqual(pending.verified_ranges, ())
        self.assertEqual(pending.pending_ranges, (KeyRange(2, 3),))
        self.assertIsNone(pending.totals)
        accept_page(cold, manifest.freeze_id, manifest.entries[2].identity, pages[2])
        verified = audit_window(cold, manifest.freeze_id, 2, 3)
        self.assertEqual(verified.rows, ())
        self.assertEqual(verified.verified_ranges, (KeyRange(2, 3),))
        self.assertEqual(verified.pending_ranges, ())
        self.assertEqual(verified.totals, WindowTotals(0, 0, 0))

    def test_base_bounds_prove_empty_outside_even_while_body_is_pending(self):
        base = self.submit_base(((1, 5, 8), (3, 11, 17))).revision_id
        _, manifest, pages = self.issue(base, 'outside')
        cold = self.open_cold()
        self.receive(cold, manifest, pages)
        result = audit_window(cold, manifest.freeze_id, 0, 5)
        self.assertEqual(result.rows, ())
        self.assertEqual(result.verified_ranges, (KeyRange(0, 1), KeyRange(4, 5)))
        self.assertEqual(result.pending_ranges, (KeyRange(1, 4),))
        self.assertIsNone(result.totals)
        self.assertEqual(audit_window(cold, manifest.freeze_id, 4, 5).totals, WindowTotals(0, 0, 0))
