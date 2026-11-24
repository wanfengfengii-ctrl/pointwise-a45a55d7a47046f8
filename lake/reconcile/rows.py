from collections.abc import Mapping
from dataclasses import dataclass

from lake.issue.pages import ColdPage, PageIdentity
from lake.revision.ranges import contains_key
from .coverage import CoverageSlice
from .provenance import AuditOrigin, make_audit_origin


@dataclass(frozen=True)
class VerifiedRow:
    key: int
    liters: int | None
    origin: AuditOrigin


def select_window_rows(slices: tuple[CoverageSlice, ...],
                       pages: Mapping[PageIdentity, ColdPage]) -> tuple[VerifiedRow, ...]:
    rows = []
    for piece in slices:
        if not piece.verified or piece.owner is None:
            continue
        page = pages[piece.owner]
        for page_position, row in enumerate(page.rows, start=1):
            if contains_key(piece.span, row.key):
                origin = make_audit_origin(page.identity, page_position, row.origin)
                rows.append(VerifiedRow(row.key, row.liters, origin))
    return tuple(sorted(rows, key=lambda row: row.key))
