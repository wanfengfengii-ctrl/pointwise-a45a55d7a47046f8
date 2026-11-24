from lake.ingest.origins import correction_origin
from lake.ingest.rows import ReadingRow, order_rows_by_key, parse_input_rows
from .ranges import KeyMove, KeyRange, contains_key
from .store import RevisionRecord


def validate_replacement(correction_id: str, span: KeyRange, rows) -> tuple[ReadingRow, ...]:
    readings = parse_input_rows(rows, lambda position: correction_origin(correction_id, position))
    if any(not contains_key(span, row.key) for row in readings):
        raise ValueError('replacement reading lies outside the declared range')
    return order_rows_by_key(readings)


def replace_rows(parent_rows: tuple[ReadingRow, ...], span: KeyRange,
                 replacement: tuple[ReadingRow, ...]) -> tuple[ReadingRow, ...]:
    survivors = tuple(row for row in parent_rows if not contains_key(span, row.key))
    return order_rows_by_key(survivors + replacement)


def shift_row(row: ReadingRow, shift: int) -> ReadingRow:
    return ReadingRow(row.key + shift, row.liters, row.origin)


def moved_rows(parent_rows: tuple[ReadingRow, ...], move: KeyMove) -> tuple[ReadingRow, ...]:
    """Shift the parent's source-band rows onto their destination keys, origins kept."""
    return order_rows_by_key(
        shift_row(row, move.shift) for row in parent_rows if contains_key(move.source, row.key)
    )


def apply_move(parent_rows: tuple[ReadingRow, ...], move: KeyMove,
               shifted: tuple[ReadingRow, ...]) -> tuple[ReadingRow, ...]:
    survivors = tuple(
        row for row in parent_rows
        if not contains_key(move.source, row.key) and not contains_key(move.dest, row.key)
    )
    return order_rows_by_key(survivors + shifted)


def materialize_revision(lineage: tuple[RevisionRecord, ...]) -> tuple[ReadingRow, ...]:
    readings = lineage[0].rows
    for revision in lineage[1:]:
        if isinstance(revision.declaration, KeyMove):
            readings = apply_move(readings, revision.declaration, revision.rows)
        elif revision.declaration is not None:
            readings = replace_rows(readings, revision.declaration, revision.rows)
        else:
            raise ValueError('non-base revision is missing a replacement declaration')
    return readings
