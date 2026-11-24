import sqlite3

from lake import get_revision, initialize_source
from lake.ingest.store import read_submission
from tests.support import LakeCase, readings


class IngestTests(LakeCase):
    def test_v1_submission_replay_and_reinitialize(self):
        incoming = ((3, 11, 17), (1, 5, 8), (2, None, 9))
        receipt = self.submit_base(incoming)
        self.assertEqual((receipt.row_count, receipt.missing_count), (3, 1))
        self.assertEqual(self.submit_base(incoming), receipt)
        initialize_source(self.source)
        self.source.close()
        self.source = self.open_source()
        self.assertEqual(self.submit_base(incoming), receipt)
        stored = read_submission(self.source, receipt.batch_id)
        self.assertEqual(readings(stored.batch.rows), ((3, 11), (1, 5), (2, None)))
        rows = get_revision(self.source, receipt.revision_id)
        self.assertEqual(readings(rows), ((1, 5), (2, None), (3, 11)))
        self.assertEqual(tuple(row.origin.position for row in rows), (8, 9, 17))
        self.assertEqual(self.source.execute('SELECT count(*) FROM revision_record').fetchone(), (1,))

    def test_v1_request_conflict_on_position_and_order(self):
        incoming = ((1, 5, 8), (2, None, 9), (3, 11, 17))
        receipt = self.submit_base(incoming)
        original = read_submission(self.source, receipt.batch_id)
        changed_position = ((1, 5, 8), (2, None, 90), (3, 11, 17))
        for changed in (changed_position, tuple(reversed(incoming))):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'different request'):
                self.submit_base(changed)
        self.assertEqual(read_submission(self.source, receipt.batch_id), original)
        self.assertEqual(get_revision(self.source, receipt.revision_id)[1].origin.position, 9)
        self.assertEqual(self.submit_base(incoming), receipt)
        self.assertEqual(self.source.execute('SELECT count(*) FROM revision_record').fetchone(), (1,))

    def test_v2_duplicates_reject_entire_batch(self):
        prior = self.submit_base()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.submit_base([(2, 6, 10), (2, 16, 11)], batch_id='duplicate')
        self.assertIsNone(read_submission(self.source, 'duplicate'))
        with self.assertRaises(KeyError):
            get_revision(self.source, 'batch:duplicate')
        self.assertEqual(readings(get_revision(self.source, prior.revision_id)), ((1, 5), (2, 7), (3, 11)))
        rejected = self.source.execute('SELECT batch_id, reason FROM station_rejection').fetchall()
        self.assertEqual(rejected, [('duplicate', 'duplicate reading key')])
        self.assertEqual(self.source.execute('SELECT count(*) FROM revision_record').fetchone(), (1,))

    def test_invalid_reading_types_preserve_original_ledger(self):
        for row in [(True, 5, 0), (1.0, 5, 0), (1, False, 0), (1, '5', 0), (1, 1.5, 0), (1, 5, -1)]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.submit_base([row])
        with self.assertRaises(KeyError):
            get_revision(self.source, 'batch:station-b1')
        self.assertEqual(self.submit_base([(1, 0, 0)]).missing_count, 0)

    def test_source_write_failure_rolls_back_base(self):
        self.source.executescript('''
            CREATE TRIGGER reject_submission BEFORE INSERT ON station_submission
            BEGIN SELECT RAISE(ABORT, 'test source insertion failure'); END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'test source insertion failure'):
            self.submit_base()
        self.assertIsNone(read_submission(self.source, 'station-b1'))
        with self.assertRaises(KeyError):
            get_revision(self.source, 'batch:station-b1')
        self.source.execute('DROP TRIGGER reject_submission')
        self.assertEqual(self.submit_base().revision_id, 'batch:station-b1')
