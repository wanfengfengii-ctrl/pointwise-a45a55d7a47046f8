"""Run the station-to-isolation handoff on the finite example day."""

from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from lake import (accept_page, amend, audit_window, fetch_bundle, freeze_table, get_revision,
                  initialize_source, open_inventory, read_page, submit)


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


def main():
    path = Path(__file__).resolve().parent / 'examples' / 'day.json'
    day = json.loads(path.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='qinglan-day-') as directory:
        run(Path(directory), day)


if __name__ == '__main__':
    main()
