from dataclasses import dataclass

from .rows import VerifiedRow


@dataclass(frozen=True)
class WindowTotals:
    row_count: int
    missing_count: int
    total_liters: int


def summarize_window(rows: tuple[VerifiedRow, ...], *, complete: bool) -> WindowTotals | None:
    if not complete:
        return None
    missing = 0
    total = 0
    for row in rows:
        if row.liters is None:
            missing += 1
        else:
            total += row.liters
    return WindowTotals(len(rows), missing, total)
