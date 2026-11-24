from dataclasses import dataclass
import sqlite3

from lake.receive.reopen import read_inventory_snapshot
from lake.revision.ranges import KeyRange, validate_range
from .coverage import coverage_ranges, resolve_coverage
from .rows import VerifiedRow, select_window_rows
from .totals import WindowTotals, summarize_window


@dataclass(frozen=True)
class WindowResult:
    freeze_id: str
    window: KeyRange
    rows: tuple[VerifiedRow, ...]
    verified_ranges: tuple[KeyRange, ...]
    pending_ranges: tuple[KeyRange, ...]
    totals: WindowTotals | None


def audit_window(db: sqlite3.Connection, freeze_id: str, lo: int, hi: int) -> WindowResult:
    """Return verified rows and completeness for one half-open frozen window."""
    window = validate_range(lo, hi)
    snapshot = read_inventory_snapshot(db, freeze_id)
    slices = resolve_coverage(window, snapshot.manifest, snapshot.pages.keys())
    verified, pending = coverage_ranges(slices)
    rows = select_window_rows(slices, snapshot.pages)
    totals = summarize_window(rows, complete=not pending)
    return WindowResult(freeze_id, window, rows, verified, pending, totals)
