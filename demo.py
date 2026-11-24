"""Run the station-to-isolation handoff on the finite example day."""

from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from lake import (accept_page, amend, amend_move, audit_window, fetch_bundle, freeze_table,
                  get_revision, initialize_source, open_inventory, read_page, submit)
from lake.issue.manifest import MoveEntry, encode_manifest


def window_record(result):
    return {
        'rows': [[row.key, row.liters] for row in result.rows],
        'verified': [[span.lo, span.hi] for span in result.verified_ranges],
        'pending': [[span.lo, span.hi] for span in result.pending_ranges],
        'totals': None if result.totals is None else asdict(result.totals),
    }


def report(case_id, inputs, expected, actual, downstream_expected, downstream_actual, code_paths, oracle):
    if actual != expected or downstream_actual != downstream_expected:
        raise AssertionError(f'{case_id} mismatch: actual={actual!r}, downstream={downstream_actual!r}')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id,
        'input': inputs,
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': code_paths,
        'oracle': oracle,
    }, ensure_ascii=False, sort_keys=True))


def run(root, day):
    with closing(sqlite3.connect(root / 'source.sqlite')) as source:
        initialize_source(source)
        submitted = submit(source, day['batch_id'], day['station'], day['day'], day['rows'])
        revision = submitted.revision_id
        for edit in day['edits']:
            lo, hi = edit['range']
            revision = amend(source, edit['id'], revision, lo, hi, edit['rows'])
        issued = freeze_table(source, 'night-shift', revision)
        manifest = fetch_bundle(source, issued.freeze_id)
        pages = tuple(read_page(source, entry.identity) for entry in manifest.entries)
        wrong_issue = freeze_table(source, 'separate-handoff', revision)
        wrong_manifest = fetch_bundle(source, wrong_issue.freeze_id)
        wrong = wrong_manifest.entries[1].identity
        wrong_payload = read_page(source, wrong)
        source_rows = [[row.key, row.liters] for row in get_revision(source, revision)]

    freeze_id = manifest.freeze_id
    cold_path = root / 'night.sqlite'
    with closing(open_inventory(cold_path)) as cold:
        accept_page(cold, manifest)
        for index in (0, 2):
            accept_page(cold, freeze_id, manifest.entries[index].identity, pages[index])
        small = audit_window(cold, freeze_id, 2, 3)
        big = audit_window(cold, freeze_id, 1, 4)
        paths = ['lake/issue/manifest.py', 'lake/receive/intake.py', 'lake/reconcile/coverage.py',
                 'lake/reconcile/rows.py', 'lake/reconcile/window.py']
        pending = {'rows': [[3, 11]], 'verified': [[2, 4]], 'pending': [[1, 2]], 'totals': None}
        report('v6', {'source': day, 'freeze_id': freeze_id, 'windows': [[2, 3], [1, 4]], 'received': [1, 3]},
               {'rows': [], 'verified': [[2, 3]], 'pending': [],
                'totals': {'row_count': 0, 'missing_count': 0, 'total_liters': 0}},
               window_record(small), pending, window_record(big), paths,
               'Later page clears key 2, missing page still owns key 1, base key 3 is unchanged.')
        rejected = False
        try:
            accept_page(cold, freeze_id, wrong, wrong_payload)
        except ValueError:
            rejected = True
        after_wrong = audit_window(cold, freeze_id, 1, 4)
        exact = manifest.entries[1].identity
        accepted = accept_page(cold, freeze_id, exact, pages[1])

    with closing(open_inventory(cold_path)) as cold:
        complete = audit_window(cold, freeze_id, 1, 4)
    report('v7', {'freeze_id': freeze_id, 'wrong_freeze_id': wrong.freeze_id, 'wanted_page': 2, 'window': [1, 4]},
           {'rejected': True, 'after_wrong': pending, 'exact_received': True},
           {'rejected': rejected, 'after_wrong': window_record(after_wrong), 'exact_received': accepted.identity == exact},
           {'window': {'rows': [[3, 11]], 'verified': [[1, 4]], 'pending': [],
                       'totals': {'row_count': 1, 'missing_count': 0, 'total_liters': 11}},
            'source_final_rows': [[3, 11]], 'origin_page': 1, 'origin_position': 17},
           {'window': window_record(complete), 'source_final_rows': source_rows,
            'origin_page': complete.rows[0].origin.page.page_no,
            'origin_position': complete.rows[0].origin.source.position},
           paths + ['lake/receive/verify.py', 'lake/receive/reopen.py', 'lake/reconcile/totals.py'],
           'After the exact page arrives, both replacements stand. Only the third base reading contributes 11 liters.')


def issue_pages(source, revision_id, request_id):
    receipt = freeze_table(source, request_id, revision_id)
    manifest = fetch_bundle(source, receipt.freeze_id)
    pages = tuple(
        None if isinstance(entry, MoveEntry) else read_page(source, entry.identity)
        for entry in manifest.entries
    )
    return manifest, pages


def run_move(root, work):
    with closing(sqlite3.connect(root / 'move-source.sqlite')) as source:
        initialize_source(source)
        base = submit(source, work['batch_id'], work['station'], work['day'], work['base_rows']).revision_id
        edit_spec = work['missing_edit']
        edit = amend(source, edit_spec['id'], base, edit_spec['lo'], edit_spec['hi'], edit_spec['rows'])
        move_spec = work['move']
        moved = amend_move(source, move_spec['id'], edit,
                           move_spec['lo'], move_spec['hi'], move_spec['dest_lo'])
        moved_account = [[row.key, row.liters] for row in get_revision(source, moved)]
        parent_account = [[row.key, row.liters] for row in get_revision(source, edit)]
        later_spec = work['later_edit']
        later = amend(source, later_spec['id'], moved,
                      later_spec['lo'], later_spec['hi'], later_spec['rows'])
        second_spec = work['second_move']
        second = amend_move(source, second_spec['id'], moved,
                            second_spec['lo'], second_spec['hi'], second_spec['dest_lo'])
        later_account = [[row.key, row.liters] for row in get_revision(source, later)]
        move_manifest, move_pages = issue_pages(source, moved, 'night-move')
        later_manifest, later_pages = issue_pages(source, later, 'night-later')
        second_manifest, second_pages = issue_pages(source, second, 'night-second')
    # The source ledger is now closed: the night shift works from frozen directories alone.
    lo, hi = work['window']
    paths = ['lake/revision/ledger.py', 'lake/revision/apply.py', 'lake/issue/manifest.py',
             'lake/reconcile/coverage.py', 'lake/reconcile/rows.py', 'lake/reconcile/window.py']

    freeze_id = move_manifest.freeze_id
    cold_path = root / 'move-night.sqlite'
    with closing(open_inventory(cold_path)) as cold:
        accept_page(cold, encode_manifest(move_manifest))
        accept_page(cold, freeze_id, move_manifest.entries[0].identity, move_pages[0])
        partial = audit_window(cold, freeze_id, lo, hi)
    report('move-disconnect-base-only',
           {'work': work, 'freeze_id': freeze_id, 'window': [lo, hi], 'received_pages': [1]},
           {'rows': [[5, 5]], 'verified': [[1, 6], [7, 8]], 'pending': [[6, 7]], 'totals': None},
           window_record(partial),
           {'moved_account': [[5, 5], [6, None], [12, 0]],
            'parent_account': [[1, 5], [2, None], [5, 7], [7, 9], [12, 0]]},
           {'moved_account': moved_account, 'parent_account': parent_account},
           paths,
           'Source closed; the vacated band verifies empty from the directory and only key 5 '
           'arrives with the base page, leaving [6,7) pending.')

    with closing(open_inventory(cold_path)) as cold:
        accept_page(cold, freeze_id, move_manifest.entries[1].identity, move_pages[1])
        full = audit_window(cold, freeze_id, lo, hi)
        key6_origin = full.rows[1].origin
    report('move-reopen-completion',
           {'freeze_id': freeze_id, 'window': [lo, hi], 'supplementary_page': 2},
           {'rows': [[5, 5], [6, None]], 'verified': [[1, 8]], 'pending': [],
            'totals': {'row_count': 2, 'missing_count': 1, 'total_liters': 5}},
           window_record(full),
           {'key6_origin_page': 2, 'key6_origin_position': 21},
           {'key6_origin_page': key6_origin.page.page_no,
            'key6_origin_position': key6_origin.source.position},
           paths + ['lake/receive/intake.py', 'lake/receive/reopen.py'],
           'Reopening the inventory keeps the registered directory and receipts; the correction '
           'page completes key 6 as a missing row and the old key 7 value stays out of the ledger.')

    later_id = later_manifest.freeze_id
    with closing(open_inventory(root / 'move-later.sqlite')) as cold:
        accept_page(cold, encode_manifest(later_manifest))
        for index in (0, 3):
            accept_page(cold, later_id, later_manifest.entries[index].identity, later_pages[index])
        later_window = audit_window(cold, later_id, lo, hi)
    report('move-later-edit',
           {'freeze_id': later_id, 'window': [lo, hi], 'received_pages': [1, 4]},
           {'rows': [[5, 5], [6, 11]], 'verified': [[1, 8]], 'pending': [],
            'totals': {'row_count': 2, 'missing_count': 0, 'total_liters': 16}},
           window_record(later_window),
           {'later_account': [[5, 5], [6, 11], [12, 0]]},
           {'later_account': later_account},
           paths, 'A later correction on the moved revision uses the new keys; the base and '
           'follow-up pages verify the whole window at 16 liters.')

    second_id = second_manifest.freeze_id
    with closing(open_inventory(root / 'move-second.sqlite')) as cold:
        accept_page(cold, encode_manifest(second_manifest))
        accept_page(cold, second_id, second_manifest.entries[0].identity, second_pages[0])
        second_partial = audit_window(cold, second_id, 1, 12)
        accept_page(cold, second_id, second_manifest.entries[1].identity, second_pages[1])
        second_full = audit_window(cold, second_id, 1, 12)
    report('move-second-move',
           {'freeze_id': second_id, 'window': [1, 12], 'received_pages': [1]},
           {'rows': [[9, 5]], 'verified': [[1, 10], [11, 12]], 'pending': [[10, 11]], 'totals': None},
           window_record(second_partial),
           {'rows': [[9, 5], [10, None]], 'verified': [[1, 12]], 'pending': [],
            'totals': {'row_count': 2, 'missing_count': 1, 'total_liters': 5}},
           window_record(second_full),
           paths, 'A second relocation shifts the band again; the same original base and '
           'correction pages still evidence the readings at keys 9 and 10.')


def main():
    path = Path(__file__).resolve().parent / 'examples' / 'day.json'
    day = json.loads(path.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='qinglan-day-') as directory:
        run(Path(directory), day)
    move_path = Path(__file__).resolve().parent / 'examples' / 'move.json'
    work = json.loads(move_path.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='qinglan-move-') as directory:
        run_move(Path(directory), work)


if __name__ == '__main__':
    main()
